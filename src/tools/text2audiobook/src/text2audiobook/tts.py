"""Qwen3-TTS (CustomVoice) loading and per-chunk WAV synthesis."""

import gc
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from text2audiobook.config import TtsConfig
from text2audiobook.gpu import resolve_tts_device
from text2audiobook.llm import CleanedChunk
from text2audiobook.logging_setup import ProgressContext

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"


@dataclass
class AudioChunk:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    chunk_index: int
    wav_path: Path


def load_tts(config: TtsConfig, *, device: str | None = None) -> Any:
    """Load Qwen3-TTS CustomVoice; device defaults to resolve_tts_device(config.device)."""
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
    if device == "cpu":
        model = Qwen3TTSModel.from_pretrained(model_id, **load_kwargs)
    else:
        try:
            model = Qwen3TTSModel.from_pretrained(
                model_id,
                attn_implementation="flash_attention_2",
                **load_kwargs,
            )
        except Exception:
            logger.info(
                "flash_attention_2 unavailable for %s; loading without it",
                model_id,
                exc_info=True,
            )
            model = Qwen3TTSModel.from_pretrained(model_id, **load_kwargs)

    logger.info(
        "Loaded Qwen3-TTS on %s (model=%s, lang=%s, voice=%s, instruct=%r)",
        device,
        model_id,
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
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def append_silence(audio: np.ndarray, silence_ms: int, sample_rate: int) -> np.ndarray:
    if silence_ms <= 0:
        return audio
    silence_frames = round(silence_ms * sample_rate / 1000)
    if silence_frames <= 0:
        return audio
    return np.concatenate([audio, np.zeros(silence_frames, dtype=np.float32)])


def synthesize_to_wav(
    model: Any,
    text: str,
    wav_path: Path,
    *,
    voice: str,
    language: str,
    instruct: str | None = None,
    chunk_silence_ms: int = 0,
) -> None:
    """Synthesize one chunk to a WAV file.

    Written via a temp file + rename so an interrupted run never leaves a
    partial WAV that resume logic would mistake for a finished chunk.
    Sample rate comes from the model (do not assume 24 kHz).
    """
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    gen_kwargs: dict[str, Any] = {
        "text": text,
        "language": language,
        "speaker": voice,
    }
    if instruct:
        gen_kwargs["instruct"] = instruct

    wavs, sample_rate = model.generate_custom_voice(**gen_kwargs)
    if not wavs:
        raise RuntimeError(f"Qwen3-TTS produced no audio for: {wav_path}")

    audio = np.asarray(wavs[0], dtype=np.float32)
    merged = append_silence(audio, chunk_silence_ms, sample_rate=int(sample_rate))
    tmp_path = wav_path.with_suffix(".tmp.wav")
    sf.write(tmp_path, merged, int(sample_rate))
    tmp_path.replace(wav_path)


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

    for i, chunk in enumerate(cleaned_chunks):
        wav_path = staging_dir / "wav" / chunk.chapter_slug / f"{chunk.chunk_index:04d}.wav"
        synthesize_to_wav(
            model,
            chunk.cleaned_text,
            wav_path,
            voice=config.voice,
            language=config.lang,
            instruct=chunk.instruct or config.instruct,
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
