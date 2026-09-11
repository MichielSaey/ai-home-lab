"""Qwen LLM loading and batched chunk cleanup for TTS."""

import gc
import hashlib
import logging
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from text2audiobook.chunking import TextChunk
from text2audiobook.config import LlmConfig
from text2audiobook.formatting import format_for_tts
from text2audiobook.logging_setup import ProgressContext

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You prepare book text for text-to-speech narration."

# Cleanup output guard: outside these bounds the LLM response is rejected
# (commentary, truncation, or runaway generation) and the raw chunk is used.
MIN_CLEANED_RATIO = 0.4
MAX_CLEANED_RATIO = 2.5


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


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_llm(config: LlmConfig) -> LoadedLlm:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise RuntimeError(f"CUDA not available — cannot load {config.model_id}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )
    tokenizer = AutoTokenizer.from_pretrained(config.model_id)
    model = AutoModelForCausalLM.from_pretrained(
        config.model_id,
        quantization_config=bnb_config,
        device_map="auto",
        dtype=torch.float16,
    )
    model.eval()
    logger.info("Loaded %s on %s", config.model_id, config.device)
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


def _build_prompt(tokenizer: Any, clean_prompt: str, text: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": clean_prompt.format(text=text)},
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
    if not cleaned or ratio < MIN_CLEANED_RATIO or ratio > MAX_CLEANED_RATIO:
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

    prompts = [_build_prompt(tokenizer, config.clean_prompt, text) for text in texts]
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


def iter_clean_chunks_batched(
    llm: LoadedLlm | None,
    chunks: list[TextChunk],
    config: LlmConfig,
    *,
    already_cleaned: Mapping[tuple[int, int], str] | None = None,
    stop: threading.Event | None = None,
    progress: ProgressContext | None = None,
) -> Iterator[CleanedChunk]:
    """Yield cleaned chunks in input order.

    Chunks present in already_cleaned (keyed by (chapter_index, chunk_index),
    e.g. from a previous run's format/chunks.jsonl) are emitted without touching the
    LLM; the rest are cleaned in batches of config.cleanup_batch_size. With no
    LLM or cleanup disabled, raw text passes through.
    """
    cache = dict(already_cleaned or {})
    use_llm = llm is not None and config.cleanup
    batch_size = max(1, config.cleanup_batch_size)
    total = len(chunks)
    emitted = 0
    pending: list[TextChunk] = []

    def to_cleaned(chunk: TextChunk, cleaned_text: str) -> CleanedChunk:
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
        )

    def flush() -> Iterator[CleanedChunk]:
        if not pending:
            return
        assert llm is not None
        cleaned_texts = clean_texts_batch(
            llm, [c.text for c in pending], config, chunks=pending
        )
        for chunk, cleaned_text in zip(pending, cleaned_texts):
            yield to_cleaned(chunk, cleaned_text)
        pending.clear()

    for chunk in chunks:
        if stop is not None and stop.is_set():
            return
        cached = cache.get((chunk.chapter_index, chunk.chunk_index))
        if cached is not None:
            yield from flush()
            yield to_cleaned(chunk, cached)
        elif not use_llm:
            yield to_cleaned(chunk, chunk.text)
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
    already_cleaned: Mapping[tuple[int, int], str] | None = None,
    progress: ProgressContext | None = None,
) -> list[CleanedChunk]:
    return list(
        iter_clean_chunks_batched(
            llm, chunks, config, already_cleaned=already_cleaned, progress=progress
        )
    )
