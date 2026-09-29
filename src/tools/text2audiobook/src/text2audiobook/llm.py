"""Qwen LLM loading, batched chunk cleanup, and TTS delivery direction."""

import gc
import hashlib
import logging
import re
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any

from text2audiobook.chunking import TextChunk
from text2audiobook.config import LlmConfig
from text2audiobook.formatting import format_for_tts
from text2audiobook.logging_setup import ProgressContext

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You prepare book text for text-to-speech narration."
DIRECTION_SYSTEM_PROMPT = (
    "You write short passage-level delivery instructions for Qwen3-TTS "
    "(VoiceDesign or CustomVoice) instruct. The global TTS instruct already sets "
    "the native-English female narrator persona; only describe pace, emotion, "
    "and emphasis for this passage."
)

# Cleanup output guard: reject empty replies or runaway generation (too long).
# There is no minimum length floor — citation-heavy chunks may shrink a lot.
MAX_CLEANED_RATIO = 2.5

# Direction instruct guard: keep short style hints, never narration dumps.
MAX_INSTRUCT_WORDS = 60
MAX_INSTRUCT_CHARS = 400
_BRACKET_TAG_RE = re.compile(r"\[[A-Za-z][^\]]*\]")


@dataclass
class LoadedLlm:
    model: Any
    tokenizer: Any
    model_id: str


@dataclass
class CleanedChunk:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    chunk_index: int
    raw_text: str
    cleaned_text: str
    instruct: str | None = None


@dataclass(frozen=True)
class FormatCacheEntry:
    """Resume cache for format windows: cleaned text plus optional instruct."""

    cleaned_text: str
    instruct: str | None = None


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_llm(
    config: LlmConfig,
    *,
    hub_prefer_local: bool = True,
    hub_offline: bool = False,
) -> LoadedLlm:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    from text2audiobook.hub import resolve_pretrained_path

    if not torch.cuda.is_available():
        raise RuntimeError(f"CUDA not available — cannot load {config.model_id}")

    model_path = resolve_pretrained_path(
        config.model_id,
        prefer_local=hub_prefer_local,
        offline=hub_offline,
    )
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        quantization_config=bnb_config,
        device_map="auto",
        dtype=torch.float16,
        local_files_only=True,
    )
    model.eval()
    logger.info("Loaded %s on %s (path=%s)", config.model_id, config.device, model_path)
    return LoadedLlm(model=model, tokenizer=tokenizer, model_id=config.model_id)


def unload_llm(llm: LoadedLlm | None) -> None:
    """Drop model references and free CUDA memory."""
    if llm is None:
        return
    import torch

    llm.model = None
    llm.tokenizer = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _build_prompt(
    tokenizer: Any,
    user_prompt: str,
    text: str,
    *,
    system: str = SYSTEM_PROMPT,
) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt.format(text=text)},
    ]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def _guard_cleaned(
    raw: str,
    cleaned: str,
    *,
    chapter_index: int | None = None,
    chunk_index: int | None = None,
    chapter_title: str | None = None,
) -> str:
    raw_words = len(raw.split())
    cleaned_words = len(cleaned.split())
    if raw_words == 0:
        return cleaned
    ratio = cleaned_words / raw_words
    if not cleaned.strip() or ratio > MAX_CLEANED_RATIO:
        where = ""
        if chapter_index is not None and chunk_index is not None:
            title = f" ({chapter_title})" if chapter_title else ""
            where = f" chapter={chapter_index} chunk={chunk_index}{title};"
        logger.warning(
            "LLM cleanup output rejected (%d -> %d words);%s falling back to raw chunk",
            raw_words,
            cleaned_words,
            where,
        )
        return raw
    return cleaned


def _guard_instruct(raw_reply: str, narration: str) -> str | None:
    """Accept a short delivery hint; reject empty, overlong, or suspicious replies."""
    cleaned = raw_reply.strip().strip("\"'`")
    if not cleaned:
        return None
    if len(cleaned) > MAX_INSTRUCT_CHARS or len(cleaned.split()) > MAX_INSTRUCT_WORDS:
        logger.warning(
            "LLM direction output rejected (too long: %d chars / %d words)",
            len(cleaned),
            len(cleaned.split()),
        )
        return None
    if _BRACKET_TAG_RE.search(cleaned):
        logger.warning("LLM direction output rejected (bracket emotion tag)")
        return None
    narration_stripped = narration.strip()
    if narration_stripped and cleaned in narration_stripped:
        logger.warning("LLM direction output rejected (copied narration)")
        return None
    if (
        narration_stripped
        and len(cleaned.split()) > 40
        and len(cleaned) > 0.5 * len(narration_stripped)
    ):
        logger.warning("LLM direction output rejected (looks like narration dump)")
        return None
    return cleaned


def clean_texts_batch(
    llm: LoadedLlm,
    texts: list[str],
    config: LlmConfig,
    *,
    chunks: list[TextChunk] | None = None,
) -> list[str]:
    """Clean a batch of texts with one generate() call (left-padded prompts)."""
    import torch

    tokenizer = llm.tokenizer
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    prompts = [
        _build_prompt(tokenizer, config.clean_prompt, text) for text in texts
    ]
    inputs = tokenizer(prompts, return_tensors="pt", padding=True).to(llm.model.device)

    with torch.inference_mode():
        output_ids = llm.model.generate(
            **inputs,
            max_new_tokens=config.max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )

    generated = output_ids[:, inputs["input_ids"].shape[1] :]
    decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
    guarded: list[str] = []
    for i, (raw, text) in enumerate(zip(texts, decoded)):
        chunk = chunks[i] if chunks is not None else None
        guarded.append(
            _guard_cleaned(
                raw,
                text.strip(),
                chapter_index=None if chunk is None else chunk.chapter_index,
                chunk_index=None if chunk is None else chunk.chunk_index,
                chapter_title=None if chunk is None else chunk.chapter_title,
            )
        )
    return guarded


def direction_texts_batch(
    llm: LoadedLlm,
    texts: list[str],
    config: LlmConfig,
) -> list[str | None]:
    """Generate per-chunk TTS instruct strings (or None when rejected)."""
    import torch

    tokenizer = llm.tokenizer
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    prompts = [
        _build_prompt(
            tokenizer,
            config.direction_prompt,
            text,
            system=DIRECTION_SYSTEM_PROMPT,
        )
        for text in texts
    ]
    inputs = tokenizer(prompts, return_tensors="pt", padding=True).to(llm.model.device)

    with torch.inference_mode():
        output_ids = llm.model.generate(
            **inputs,
            max_new_tokens=config.direction_max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )

    generated = output_ids[:, inputs["input_ids"].shape[1] :]
    decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
    return [_guard_instruct(reply, narration) for narration, reply in zip(texts, decoded)]


def _cache_cleaned_text(
    already_cleaned: Mapping[tuple[int, int], FormatCacheEntry | str] | None,
    key: tuple[int, int],
) -> str | None:
    if already_cleaned is None:
        return None
    entry = already_cleaned.get(key)
    if entry is None:
        return None
    if isinstance(entry, FormatCacheEntry):
        return entry.cleaned_text
    return entry


def _cache_instruct(
    already_cleaned: Mapping[tuple[int, int], FormatCacheEntry | str] | None,
    key: tuple[int, int],
) -> str | None:
    if already_cleaned is None:
        return None
    entry = already_cleaned.get(key)
    if isinstance(entry, FormatCacheEntry):
        return entry.instruct
    return None


def iter_clean_chunks_batched(
    llm: LoadedLlm | None,
    chunks: list[TextChunk],
    config: LlmConfig,
    *,
    already_cleaned: Mapping[tuple[int, int], FormatCacheEntry | str] | None = None,
    stop: threading.Event | None = None,
    progress: ProgressContext | None = None,
) -> Iterator[CleanedChunk]:
    """Yield cleaned chunks in input order.

    Chunks present in already_cleaned (keyed by (chapter_index, chunk_index),
    e.g. from a previous run's format/chunks.jsonl) are emitted without touching the
    LLM; the rest are cleaned in batches of config.cleanup_batch_size. With no
    LLM or cleanup disabled, raw text passes through. Cached instruct (if any)
    is restored onto the CleanedChunk.
    """
    cache = already_cleaned or {}
    use_llm = llm is not None and config.cleanup
    batch_size = max(1, config.cleanup_batch_size)
    total = len(chunks)
    emitted = 0
    pending: list[TextChunk] = []

    def to_cleaned(
        chunk: TextChunk,
        cleaned_text: str,
        *,
        instruct: str | None = None,
    ) -> CleanedChunk:
        nonlocal emitted
        emitted += 1
        if progress is not None:
            logger.info(
                "%s",
                progress.format(
                    "format",
                    unit_done=emitted,
                    total_chunks=total,
                    chapter_idx=chunk.chapter_index,
                    chapter_title=chunk.chapter_title,
                    chapter_unit=chunk.chunk_index + 1,
                ),
            )
        else:
            logger.info(
                "[%d/%d] format window %d of '%s'",
                emitted,
                total,
                chunk.chunk_index,
                chunk.chapter_title,
            )
        return CleanedChunk(
            chapter_index=chunk.chapter_index,
            chapter_title=chunk.chapter_title,
            chapter_slug=chunk.chapter_slug,
            chunk_index=chunk.chunk_index,
            raw_text=chunk.text,
            cleaned_text=format_for_tts(
                cleaned_text,
                chapter_title=chunk.chapter_title,
                source_kind=chunk.source_kind,
            ),
            instruct=instruct,
        )

    def flush() -> Iterator[CleanedChunk]:
        if not pending:
            return
        assert llm is not None
        cleaned_texts = clean_texts_batch(
            llm, [c.text for c in pending], config, chunks=pending
        )
        for chunk, cleaned_text in zip(pending, cleaned_texts):
            key = (chunk.chapter_index, chunk.chunk_index)
            yield to_cleaned(
                chunk,
                cleaned_text,
                instruct=_cache_instruct(cache, key),
            )
        pending.clear()

    for chunk in chunks:
        if stop is not None and stop.is_set():
            return
        key = (chunk.chapter_index, chunk.chunk_index)
        cached = _cache_cleaned_text(cache, key)
        if cached is not None:
            yield from flush()
            yield to_cleaned(chunk, cached, instruct=_cache_instruct(cache, key))
        elif not use_llm:
            yield to_cleaned(chunk, chunk.text, instruct=_cache_instruct(cache, key))
        else:
            pending.append(chunk)
            if len(pending) >= batch_size:
                yield from flush()

    yield from flush()


def clean_chunks_batched(
    llm: LoadedLlm | None,
    chunks: list[TextChunk],
    config: LlmConfig,
    *,
    already_cleaned: Mapping[tuple[int, int], FormatCacheEntry | str] | None = None,
    progress: ProgressContext | None = None,
) -> list[CleanedChunk]:
    return list(
        iter_clean_chunks_batched(
            llm, chunks, config, already_cleaned=already_cleaned, progress=progress
        )
    )


def apply_direction_pass(
    llm: LoadedLlm | None,
    chunks: list[CleanedChunk],
    config: LlmConfig,
    *,
    progress: ProgressContext | None = None,
) -> list[CleanedChunk]:
    """Fill missing ``instruct`` fields via a second LLM pass (passage delivery).

    Chunks that already have a non-empty instruct (e.g. from resume cache) are
    left unchanged. Rejected model output leaves instruct as None so speak falls
    back to the global ``tts.instruct``.
    """
    if llm is None or not config.direction or not chunks:
        return chunks

    batch_size = max(1, config.cleanup_batch_size)
    need_indices = [
        index for index, chunk in enumerate(chunks) if not (chunk.instruct or "").strip()
    ]
    if not need_indices:
        logger.info("Direction: all %d window(s) already have instruct", len(chunks))
        return chunks

    logger.info(
        "Direction pass: generating instruct for %d of %d window(s)",
        len(need_indices),
        len(chunks),
    )
    updated = list(chunks)
    total = len(need_indices)
    done = 0
    for start in range(0, len(need_indices), batch_size):
        batch_idx = need_indices[start : start + batch_size]
        batch_chunks = [updated[i] for i in batch_idx]
        instructs = direction_texts_batch(
            llm, [chunk.cleaned_text for chunk in batch_chunks], config
        )
        for index, instruct in zip(batch_idx, instructs):
            updated[index] = replace(updated[index], instruct=instruct)
            done += 1
            chunk = updated[index]
            if progress is not None:
                logger.info(
                    "%s",
                    progress.format(
                        "direction",
                        unit_done=done,
                        total_chunks=total,
                        chapter_idx=chunk.chapter_index,
                        chapter_title=chunk.chapter_title,
                        chapter_unit=chunk.chunk_index + 1,
                    ),
                )
            else:
                logger.info(
                    "[%d/%d] direction window %d of '%s'",
                    done,
                    total,
                    chunk.chunk_index,
                    chunk.chapter_title,
                )
    return updated
