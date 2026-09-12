"""Qwen3-TTS (Base / VoiceDesign / CustomVoice) loading and per-chunk WAV synthesis."""

import gc
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

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
    if device == "cpu":
        model = Qwen3TTSModel.from_pretrained(model_id, **load_kwargs)
    else:
        use_flash = False
        try:
            import flash_attn  # noqa: F401

            use_flash = True
        except ImportError:
            pass
        if use_flash:
            try:
                model = Qwen3TTSModel.from_pretrained(
                    model_id,
                    attn_implementation="flash_attention_2",
                    **load_kwargs,
                )
            except Exception:
                logger.info(
                    "flash_attention_2 failed for %s; loading without it",
                    model_id,
                )
                model = Qwen3TTSModel.from_pretrained(model_id, **load_kwargs)
        else:
            logger.info(
                "flash_attn not installed; loading %s without flash_attention_2",
                model_id,
            )
            model = Qwen3TTSModel.from_pretrained(model_id, **load_kwargs)

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
    """Synthesize one chunk to a WAV file.

    Written via a temp file + rename so an interrupted run never leaves a
    partial WAV that resume logic would mistake for a finished chunk.
    Sample rate comes from the model (do not assume 24 kHz).

    Base uses ``generate_voice_clone`` (ref audio + transcript, or a prompt).
    VoiceDesign uses ``generate_voice_design`` (instruct required; no speaker).
    CustomVoice uses ``generate_custom_voice`` with a catalog speaker.
    """
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    if is_base(model_id):
        gen_kwargs: dict[str, Any] = {
            "text": text,
            "language": language,
        }
        if voice_clone_prompt is not None:
            gen_kwargs["voice_clone_prompt"] = voice_clone_prompt
            logger.info("TTS API: generate_voice_clone (voice_clone_prompt)")
        else:
            if ref_audio is None:
                raise ValueError(
                    "Base voice cloning requires ref_audio or voice_clone_prompt "
                    "(set tts.ref_audio)"
                )
            gen_kwargs["ref_audio"] = str(ref_audio)
            gen_kwargs["ref_text"] = ref_text
            gen_kwargs["x_vector_only_mode"] = x_vector_only
            logger.info("TTS API: generate_voice_clone (ref_audio)")
        wavs, sample_rate = model.generate_voice_clone(**gen_kwargs)
    elif is_voice_design(model_id):
        resolved_instruct = instruct
        if not (resolved_instruct and str(resolved_instruct).strip()):
            resolved_instruct = DEFAULT_TTS_INSTRUCT
            logger.warning(
                "VoiceDesign requires instruct; falling back to DEFAULT_TTS_INSTRUCT"
            )
        if not (resolved_instruct and str(resolved_instruct).strip()):
            raise ValueError(
                "VoiceDesign synthesis requires a non-empty instruct "
                "(set tts.instruct or per-chunk direction)"
            )
        logger.info("TTS API: generate_voice_design (no speaker)")
        wavs, sample_rate = model.generate_voice_design(
            text=text,
            language=language,
            instruct=resolved_instruct,
        )
    else:
        gen_kwargs = {
            "text": text,
            "language": language,
            "speaker": voice,
        }
        if instruct and supports_instruct(model_id):
            gen_kwargs["instruct"] = instruct
        elif instruct and not supports_instruct(model_id):
            logger.debug(
                "Ignoring instruct for %s (no instruction control)",
                model_id,
            )
        logger.info("TTS API: generate_custom_voice (speaker=%s)", voice)
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
