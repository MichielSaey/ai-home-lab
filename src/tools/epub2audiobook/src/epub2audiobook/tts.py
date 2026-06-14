"""Kokoro TTS loading and per-chunk WAV synthesis."""

import gc
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from epub2audiobook.config import TtsConfig
from epub2audiobook.gpu import resolve_tts_device
from epub2audiobook.llm import CleanedChunk
from epub2audiobook.logging_setup import ProgressContext

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"


@dataclass
class AudioChunk:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    chunk_index: int
    wav_path: Path


def _ensure_spacy_model() -> None:
    """Kokoro's English G2P needs en_core_web_sm; fail fast with a clear message."""
    import spacy

    try:
        spacy.load("en_core_web_sm")
    except OSError as exc:
        raise RuntimeError(
            "spaCy model en_core_web_sm is required for Kokoro. "
            "Install with: uv sync --group epub-audiobook"
        ) from exc


def load_kokoro(config: TtsConfig, *, device: str | None = None) -> Any:
    """Load the Kokoro pipeline; device defaults to resolve_tts_device(config.device)."""
    import torch
    from kokoro import KPipeline

    _ensure_spacy_model()

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if device is None:
        device = resolve_tts_device(config.device)

    pipeline = KPipeline(lang_code=config.lang, device=device)
    logger.info(
        "Loaded Kokoro on %s (lang=%s, voice=%s, speed=%s)",
        device,
        config.lang,
        config.voice,
        config.speed,
    )
    if device == "cpu":
        logger.info("GPU cuFFT unavailable — Kokoro runs on CPU (~82M params).")
    return pipeline


def unload_kokoro(kokoro: Any) -> None:
    """Drop the pipeline's model and free CUDA memory."""
    if kokoro is None:
        return
    import torch

    if getattr(kokoro, "model", None) is not None:
        try:
            kokoro.model = None
        except AttributeError:
            pass
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def append_silence(audio: np.ndarray, silence_ms: int, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    if silence_ms <= 0:
        return audio
    silence_frames = round(silence_ms * sample_rate / 1000)
    if silence_frames <= 0:
        return audio
    return np.concatenate([audio, np.zeros(silence_frames, dtype=np.float32)])


def synthesize_to_wav(
    kokoro: Any,
    text: str,
    wav_path: Path,
    *,
    voice: str,
    speed: float,
    chunk_silence_ms: int = 0,
) -> None:
    """Synthesize one chunk to a WAV file.

    Written via a temp file + rename so an interrupted run never leaves a
    partial WAV that resume logic would mistake for a finished chunk.
    """
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    audio_parts: list[np.ndarray] = []
    for _, _, audio in kokoro(text, voice=voice, speed=speed):
        if audio is None:
            continue
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        audio_parts.append(np.asarray(audio, dtype=np.float32))

    if not audio_parts:
        raise RuntimeError(f"Kokoro produced no audio for: {wav_path}")

    merged = append_silence(np.concatenate(audio_parts), chunk_silence_ms)
    tmp_path = wav_path.with_suffix(".tmp.wav")
    sf.write(tmp_path, merged, SAMPLE_RATE)
    tmp_path.replace(wav_path)


def synthesize_chunks(
    kokoro: Any,
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

    for i, chunk in enumerate(cleaned_chunks):
        wav_path = staging_dir / "wav" / chunk.chapter_slug / f"{chunk.chunk_index:04d}.wav"
        synthesize_to_wav(
            kokoro,
            chunk.cleaned_text,
            wav_path,
            voice=config.voice,
            speed=config.speed,
            chunk_silence_ms=chunk_silence_ms,
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
