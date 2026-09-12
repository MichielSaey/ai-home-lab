"""Qwen3-TTS (Base / VoiceDesign / CustomVoice) loading and per-chunk WAV synthesis."""

import gc
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import soundfile as sf

from text2audiobook.batch_vram import batch_fits_vram, batch_vram_cost
from text2audiobook.config import DEFAULT_TTS_INSTRUCT, TtsConfig
from text2audiobook.gpu import resolve_tts_device
from text2audiobook.llm import CleanedChunk
from text2audiobook.logging_setup import ProgressContext

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"


@dataclass
class AudioChunk:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    chunk_index: int
    wav_path: Path


def is_voice_design(model_id: str | None) -> bool:
    """True when model_id names a VoiceDesign checkpoint."""
    return "VoiceDesign" in (model_id or "")


def is_custom_voice(model_id: str | None) -> bool:
    """True when model_id names a CustomVoice checkpoint."""
    return "CustomVoice" in (model_id or "")


def is_base(model_id: str | None) -> bool:
    """True when model_id names a Base (voice-clone) checkpoint."""
    mid = model_id or ""
    return "Base" in mid and not is_custom_voice(mid) and not is_voice_design(mid)


def supports_instruct(model_id: str | None) -> bool:
    """VoiceDesign and 1.7B CustomVoice accept instruct; Base and 0.6B CustomVoice do not."""
    if is_base(model_id):
        return False
    if is_voice_design(model_id):
        return True
    return is_custom_voice(model_id) and "0.6B" not in (model_id or "")


def compose_instruct(base: str | None, direction: str | None) -> str | None:
    """Join global TTS persona instruct with optional per-chunk direction."""
    parts = [p.strip() for p in (base, direction) if p and str(p).strip()]
    return " ".join(parts) if parts else None


def _ensure_tts_pad_token_id(model: Any) -> None:
    """Set generation_config.pad_token_id from eos when missing.

    Without this, Hugging Face logs
    ``Setting pad_token_id to eos_token_id:… for open-end generation.``
    on every generate call.
    """
    inner = getattr(model, "model", model)
    gen_cfg = getattr(inner, "generation_config", None)
    if gen_cfg is None:
        return
    if getattr(gen_cfg, "pad_token_id", None) is not None:
        return
    eos = getattr(gen_cfg, "eos_token_id", None)
    if eos is None:
        return
    if isinstance(eos, (list, tuple)):
        if not eos:
            return
        gen_cfg.pad_token_id = int(eos[0])
    else:
        gen_cfg.pad_token_id = int(eos)


def load_tts(config: TtsConfig, *, device: str | None = None) -> Any:
    """Load Qwen3-TTS; device defaults to resolve_tts_device(config.device)."""
    import torch
    from qwen_tts import Qwen3TTSModel

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if device is None:
        device = resolve_tts_device(config.device)

    device_map = "cpu" if device == "cpu" else "cuda:0"
    # Qwen3-TTS expects float32 on CPU; bfloat16 on CUDA.
    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    load_kwargs: dict[str, Any] = {
        "device_map": device_map,
        "dtype": dtype,
    }

    model_id = config.model_id
    # Do not request flash_attention_2: when flash_attn is missing, transformers
    # raises a loud ImportError that looks like a crash. Eager attention is fine.
    model = Qwen3TTSModel.from_pretrained(model_id, **load_kwargs)
    _ensure_tts_pad_token_id(model)

    if is_base(model_id):
        mode = "Base"
    elif is_voice_design(model_id):
        mode = "VoiceDesign"
    else:
        mode = "CustomVoice"
    logger.info(
        "Loaded Qwen3-TTS on %s (model=%s, mode=%s, lang=%s, voice=%s, instruct=%r)",
        device,
        model_id,
        mode,
        config.lang,
        config.voice,
        config.instruct,
    )
    if device == "cpu":
        logger.info("TTS running on CPU (CUDA unavailable).")
    return model


def unload_tts(model: Any) -> None:
    """Drop the TTS model and free CUDA memory."""
    if model is None:
        return
    import torch

    for attr in ("model", "processor", "tokenizer"):
        if getattr(model, attr, None) is not None:
            try:
                setattr(model, attr, None)
            except AttributeError:
                pass
    del model
    gc.collect()
    if torch.cuda.is_available():
        try:
            torch.cuda.synchronize()
        except Exception:
            pass
        torch.cuda.empty_cache()
    gc.collect()


def reload_tts(config: TtsConfig, old_model: Any, *, device: str | None = None) -> Any:
    """Unload old model, hard-clear CUDA, load a fresh TTS model.

    Callers must drop their own live references (e.g. ``tts_slot[0] = None``)
    before calling so the old weights are not dual-resident during load.
    """
    unload_tts(old_model)
    old_model = None
    import torch

    # Extra pass after unload (matches cli calibration _hard_unload) to nudge
    # the allocator into releasing fragmented blocks before from_pretrained.
    gc.collect()
    if torch.cuda.is_available():
        try:
            torch.cuda.synchronize()
        except Exception:
            pass
        torch.cuda.empty_cache()
    gc.collect()
    return load_tts(config, device=device)


def append_silence(audio: np.ndarray, silence_ms: int, sample_rate: int) -> np.ndarray:
    if silence_ms <= 0:
        return audio
    silence_frames = round(silence_ms * sample_rate / 1000)
    if silence_frames <= 0:
        return audio
    return np.concatenate([audio, np.zeros(silence_frames, dtype=np.float32)])


def create_voice_clone_prompt(
    model: Any,
    *,
    ref_audio: Path,
    ref_text: str | None,
    x_vector_only: bool = False,
) -> Any:
    """Build a reusable Base-model voice-clone prompt from reference audio."""
    return model.create_voice_clone_prompt(
        ref_audio=str(ref_audio),
        ref_text=ref_text,
        x_vector_only_mode=x_vector_only,
    )


def iter_speak_batches(
    units: Sequence[Any],
    *,
    max_chars: int,
    max_items: int,
    max_pad: int = 0,
    vram_overhead: int = 0,
) -> Iterator[list[Any]]:
    """Pack units by length-sorted contiguous prefixes under VRAM/chars/items.

    Sorts by length **descending** (then original index), then greedily cuts
    contiguous prefixes that fit all active limits. Longest units run first so
    hard batches hit a fresher GPU and OOM fails early. Primary VRAM constraint
    is ``n * (max(lens) + vram_overhead) <= max_pad`` when ``max_pad > 0``
    (``max_pad`` is the calibrated ``batch_max_pad_chars`` budget). Never splits
    a unit. ``max_chars`` / ``max_items`` / ``max_pad`` <= 0 means no limit on
    that dimension. A single oversized unit still forms its own batch.
    """
    ordered = [
        unit
        for _, unit in sorted(
            enumerate(units),
            key=lambda pair: (-len(pair[1].text), pair[0]),
        )
    ]
    i = 0
    n = len(ordered)
    while i < n:
        batch: list[Any] = [ordered[i]]
        batch_lens = [len(ordered[i].text)]
        batch_sum = batch_lens[0]
        i += 1
        while i < n:
            candidate = ordered[i]
            cand_len = len(candidate.text)
            new_lens = batch_lens + [cand_len]
            new_sum = batch_sum + cand_len
            if max_chars > 0 and new_sum > max_chars:
                break
            if not batch_fits_vram(
                new_lens,
                budget_chars=max_pad,
                overhead_chars=vram_overhead,
                max_items=max_items,
            ):
                break
            batch.append(candidate)
            batch_lens = new_lens
            batch_sum = new_sum
            i += 1
        yield batch


def _normalize_instruct_list(
    instruct: str | None | Sequence[str | None],
    n: int,
) -> list[str | None]:
    if isinstance(instruct, (str, type(None))):
        return [instruct] * n
    values = list(instruct)
    if len(values) != n:
        raise ValueError(
            f"instruct list length {len(values)} does not match batch size {n}"
        )
    return values


def _resolve_voice_design_instruct(instruct: str | None) -> str:
    resolved = instruct
    if not (resolved and str(resolved).strip()):
        resolved = DEFAULT_TTS_INSTRUCT
        logger.warning(
            "VoiceDesign requires instruct; falling back to DEFAULT_TTS_INSTRUCT"
        )
    if not (resolved and str(resolved).strip()):
        raise ValueError(
            "VoiceDesign synthesis requires a non-empty instruct "
            "(set tts.instruct or per-chunk direction)"
        )
    return resolved


def _write_wav_atomic(
    audio: np.ndarray,
    wav_path: Path,
    *,
    sample_rate: int,
    chunk_silence_ms: int,
) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    merged = append_silence(
        np.asarray(audio, dtype=np.float32),
        chunk_silence_ms,
        sample_rate=sample_rate,
    )
    tmp_path = wav_path.with_suffix(".tmp.wav")
    sf.write(tmp_path, merged, sample_rate)
    tmp_path.replace(wav_path)


def is_cuda_oom(exc: BaseException) -> bool:
    """True for torch CUDA OOM or RuntimeError mentioning out of memory."""
    try:
        import torch

        if isinstance(exc, torch.cuda.OutOfMemoryError):
            return True
    except Exception:
        pass
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


# Backward-compatible alias for internal callers (batch_vram, synthesize retries).
_is_cuda_oom = is_cuda_oom


def _cuda_oom_cleanup() -> None:
    """GC + synchronize + empty CUDA cache after OOM; swallow cleanup errors."""
    try:
        import gc

        gc.collect()
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
    except Exception:
        pass


def _split_instruct_for_halves(
    instruct: str | None | Sequence[str | None],
    mid: int,
    n: int,
) -> tuple[str | None | list[str | None], str | None | list[str | None]]:
    if isinstance(instruct, (str, type(None))):
        return instruct, instruct
    values = list(instruct)
    if len(values) != n:
        raise ValueError(
            f"instruct list length {len(values)} does not match batch size {n}"
        )
    return values[:mid], values[mid:]


def _format_batch_log(
    *,
    n: int,
    texts: Sequence[str],
    batch_max_chars: int = 0,
    batch_max_items: int = 0,
    batch_max_pad_chars: int = 0,
    batch_vram_overhead: int = 0,
) -> str:
    """Human-readable batch size breakdown for TTS logs."""
    sizes = [len(t) for t in texts]
    total = sum(sizes)
    parts = [f"batch_size={n}"]
    if batch_max_items > 0:
        parts[0] = f"batch_size={n}/{batch_max_items}"
    if batch_max_chars > 0:
        parts.append(f"chars={total}/{batch_max_chars}")
    else:
        parts.append(f"chars={total}")
    if batch_max_pad_chars > 0:
        vram_cost = batch_vram_cost(sizes, overhead_chars=batch_vram_overhead)
        parts.append(f"vram={vram_cost}/{batch_max_pad_chars}")
        if batch_vram_overhead:
            parts.append(f"oh={batch_vram_overhead}")
    parts.append("[" + ",".join(str(s) for s in sizes) + "]")
    return " ".join(parts)


def synthesize_batch_to_wavs(
    model: Any,
    items: list[tuple[str, Path]],
    *,
    voice: str,
    language: str,
    instruct: str | None | Sequence[str | None] = None,
    chunk_silence_ms: int = 0,
    model_id: str | None = None,
    voice_clone_prompt: Any | None = None,
    ref_audio: Path | str | None = None,
    ref_text: str | None = None,
    x_vector_only: bool = False,
    batch_max_chars: int = 0,
    batch_max_items: int = 0,
    batch_max_pad_chars: int = 0,
    batch_vram_overhead: int = 0,
    on_oom: Literal["split", "raise"] = "split",
) -> None:
    """Synthesize one or more chunks in a single generate_* call; write one WAV each.

    Written via temp file + rename so an interrupted run never leaves a partial WAV.
    Sample rate comes from the model (do not assume 24 kHz).
    On CUDA OOM with ``on_oom=\"split\"`` (default): GC + synchronize + empty_cache,
    then either retry once (n==1) or halve the batch and recurse (n>1).
    With ``on_oom=\"raise\"``: cleanup then re-raise (used by VRAM calibration).
    """
    if not items:
        return

    texts = [text for text, _ in items]
    paths = [path for _, path in items]
    n = len(items)
    languages = [language] * n
    instruct_list = _normalize_instruct_list(instruct, n)
    common_kwargs: dict[str, Any] = {
        "voice": voice,
        "language": language,
        "chunk_silence_ms": chunk_silence_ms,
        "model_id": model_id,
        "voice_clone_prompt": voice_clone_prompt,
        "ref_audio": ref_audio,
        "ref_text": ref_text,
        "x_vector_only": x_vector_only,
        "batch_max_chars": batch_max_chars,
        "batch_max_items": batch_max_items,
        "batch_max_pad_chars": batch_max_pad_chars,
        "batch_vram_overhead": batch_vram_overhead,
        "on_oom": on_oom,
    }
    batch_log = _format_batch_log(
        n=n,
        texts=texts,
        batch_max_chars=batch_max_chars,
        batch_max_items=batch_max_items,
        batch_max_pad_chars=batch_max_pad_chars,
        batch_vram_overhead=batch_vram_overhead,
    )

    def _run_generate() -> tuple[Any, Any]:
        if is_base(model_id):
            gen_kwargs: dict[str, Any] = {
                "text": texts,
                "language": languages,
            }
            if voice_clone_prompt is not None:
                gen_kwargs["voice_clone_prompt"] = voice_clone_prompt
                logger.info("TTS API: generate_voice_clone %s", batch_log)
            else:
                if ref_audio is None:
                    raise ValueError(
                        "Base voice cloning requires ref_audio or voice_clone_prompt "
                        "(set tts.ref_audio)"
                    )
                gen_kwargs["ref_audio"] = str(ref_audio)
                gen_kwargs["ref_text"] = ref_text
                gen_kwargs["x_vector_only_mode"] = x_vector_only
                logger.info("TTS API: generate_voice_clone %s", batch_log)
            return model.generate_voice_clone(**gen_kwargs)
        if is_voice_design(model_id):
            resolved = [_resolve_voice_design_instruct(value) for value in instruct_list]
            logger.info("TTS API: generate_voice_design %s", batch_log)
            return model.generate_voice_design(
                text=texts,
                language=languages,
                instruct=resolved,
            )
        gen_kwargs = {
            "text": texts,
            "language": languages,
            "speaker": voice,
        }
        if supports_instruct(model_id):
            if any(value and str(value).strip() for value in instruct_list):
                gen_kwargs["instruct"] = instruct_list
        elif any(value and str(value).strip() for value in instruct_list):
            logger.debug(
                "Ignoring instruct for %s (no instruction control)",
                model_id,
            )
        logger.info(
            "TTS API: generate_custom_voice %s speaker=%s",
            batch_log,
            voice,
        )
        return model.generate_custom_voice(**gen_kwargs)

    try:
        wavs, sample_rate = _run_generate()
    except Exception as exc:
        if not _is_cuda_oom(exc):
            raise
        _cuda_oom_cleanup()
        if on_oom == "raise":
            raise
        if n == 1:
            logger.warning(
                "CUDA OOM on TTS %s; retrying once after cleanup",
                batch_log,
            )
            try:
                wavs, sample_rate = _run_generate()
            except Exception as retry_exc:
                if not _is_cuda_oom(retry_exc):
                    raise
                _cuda_oom_cleanup()
                raise
        else:
            mid = n // 2
            logger.warning(
                "CUDA OOM on TTS %s; splitting into %d + %d",
                batch_log,
                mid,
                n - mid,
            )
            left_instruct, right_instruct = _split_instruct_for_halves(instruct, mid, n)
            synthesize_batch_to_wavs(
                model,
                items[:mid],
                instruct=left_instruct,
                **common_kwargs,
            )
            synthesize_batch_to_wavs(
                model,
                items[mid:],
                instruct=right_instruct,
                **common_kwargs,
            )
            return

    if wavs is None:
        raise RuntimeError(f"Qwen3-TTS produced no audio for batch of {n} texts")
    if len(wavs) != n:
        raise RuntimeError(
            f"Qwen3-TTS returned {len(wavs)} wav(s) for {n} text(s); "
            "batch size mismatch"
        )

    sample_rate_i = int(sample_rate)
    for audio, wav_path in zip(wavs, paths, strict=True):
        _write_wav_atomic(
            audio,
            wav_path,
            sample_rate=sample_rate_i,
            chunk_silence_ms=chunk_silence_ms,
        )


def synthesize_to_wav(
    model: Any,
    text: str,
    wav_path: Path,
    *,
    voice: str,
    language: str,
    instruct: str | None = None,
    chunk_silence_ms: int = 0,
    model_id: str | None = None,
    voice_clone_prompt: Any | None = None,
    ref_audio: Path | str | None = None,
    ref_text: str | None = None,
    x_vector_only: bool = False,
) -> None:
    """Synthesize one chunk to a WAV file (batch of size 1)."""
    synthesize_batch_to_wavs(
        model,
        [(text, wav_path)],
        voice=voice,
        language=language,
        instruct=instruct,
        chunk_silence_ms=chunk_silence_ms,
        model_id=model_id,
        voice_clone_prompt=voice_clone_prompt,
        ref_audio=ref_audio,
        ref_text=ref_text,
        x_vector_only=x_vector_only,
    )


def synthesize_chunks(
    model: Any,
    cleaned_chunks: Sequence[CleanedChunk],
    config: TtsConfig,
    staging_dir: Path,
    *,
    chunk_silence_ms: int = 0,
    progress: ProgressContext | None = None,
) -> list[AudioChunk]:
    """Synthesize every chunk to <staging_dir>/wav/<chapter_slug>/NNNN.wav."""
    audio_chunks: list[AudioChunk] = []
    total = len(cleaned_chunks)

    voice_clone_prompt = None
    ref_audio_path: Path | None = None
    if is_base(config.model_id):
        if not config.ref_audio:
            raise ValueError("Base voice cloning requires tts.ref_audio")
        ref_audio_path = Path(config.ref_audio)
        if not ref_audio_path.is_file():
            raise ValueError(f"tts.ref_audio not found: {ref_audio_path}")
        if not config.x_vector_only and not (config.ref_text and config.ref_text.strip()):
            raise ValueError(
                "Base voice cloning requires non-empty tts.ref_text "
                "unless tts.x_vector_only is true"
            )
        voice_clone_prompt = create_voice_clone_prompt(
            model,
            ref_audio=ref_audio_path,
            ref_text=config.ref_text,
            x_vector_only=config.x_vector_only,
        )

    for i, chunk in enumerate(cleaned_chunks):
        wav_path = staging_dir / "wav" / chunk.chapter_slug / f"{chunk.chunk_index:04d}.wav"
        synthesize_to_wav(
            model,
            chunk.cleaned_text,
            wav_path,
            voice=config.voice,
            language=config.lang,
            instruct=compose_instruct(config.instruct, chunk.instruct),
            chunk_silence_ms=chunk_silence_ms,
            model_id=config.model_id,
            voice_clone_prompt=voice_clone_prompt,
            ref_audio=ref_audio_path,
            ref_text=config.ref_text,
            x_vector_only=config.x_vector_only,
        )
        audio_chunks.append(
            AudioChunk(
                chapter_index=chunk.chapter_index,
                chapter_title=chunk.chapter_title,
                chapter_slug=chunk.chapter_slug,
                chunk_index=chunk.chunk_index,
                wav_path=wav_path,
            )
        )
        if progress is not None:
            logger.info(
                "%s",
                progress.format(
                    "tts",
                    chunk_idx=chunk.chunk_index,
                    chapter_title=chunk.chapter_title,
                    total_chunks=total,
                ),
            )
        else:
            logger.info("[%d/%d] %s", i + 1, total, wav_path)

    return audio_chunks
