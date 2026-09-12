"""Unit tests for VoiceDesign / CustomVoice TTS helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from text2audiobook.config import DEFAULT_TTS_INSTRUCT
from text2audiobook.tts import (
    compose_instruct,
    is_custom_voice,
    is_voice_design,
    synthesize_to_wav,
)


def test_compose_instruct_joins_base_and_direction() -> None:
    assert compose_instruct(None, None) is None
    assert compose_instruct("", "  ") is None
    assert compose_instruct("Base persona.", None) == "Base persona."
    assert compose_instruct(None, "Calm pace.") == "Calm pace."
    assert (
        compose_instruct("Base persona.", "Calm pace.")
        == "Base persona. Calm pace."
    )
    assert compose_instruct("  Base.  ", "  Direction.  ") == "Base. Direction."


def test_is_voice_design_and_custom_voice() -> None:
    assert is_voice_design("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    assert not is_voice_design("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
    assert is_custom_voice("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
    assert not is_custom_voice("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    assert not is_voice_design(None)


def test_synthesize_routes_to_voice_design(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_voice_design.return_value = ([np.zeros(8, dtype=np.float32)], 24000)
    model.generate_custom_voice.side_effect = AssertionError("should not call CustomVoice")

    wav_path = tmp_path / "out.wav"

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    synthesize_to_wav(
        model,
        "Hello world.",
        wav_path,
        voice="designed",
        language="English",
        instruct="Native English female narrator.",
        model_id="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    )
    model.generate_voice_design.assert_called_once()
    kwargs = model.generate_voice_design.call_args.kwargs
    assert kwargs["text"] == "Hello world."
    assert kwargs["language"] == "English"
    assert kwargs["instruct"] == "Native English female narrator."
    assert "speaker" not in kwargs
    model.generate_custom_voice.assert_not_called()
    assert wav_path.exists()


def test_synthesize_voice_design_falls_back_default_instruct(
    tmp_path: Path, monkeypatch
) -> None:
    model = MagicMock()
    model.generate_voice_design.return_value = ([np.zeros(4, dtype=np.float32)], 24000)

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    synthesize_to_wav(
        model,
        "Hi.",
        tmp_path / "a.wav",
        voice="designed",
        language="English",
        instruct=None,
        model_id="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    )
    assert (
        model.generate_voice_design.call_args.kwargs["instruct"] == DEFAULT_TTS_INSTRUCT
    )


def test_synthesize_routes_to_custom_voice(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_custom_voice.return_value = ([np.zeros(8, dtype=np.float32)], 24000)
    model.generate_voice_design.side_effect = AssertionError("should not call VoiceDesign")

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    synthesize_to_wav(
        model,
        "Hello.",
        tmp_path / "cv.wav",
        voice="Ryan",
        language="English",
        instruct="Calm pace.",
        model_id="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    )
    model.generate_custom_voice.assert_called_once()
    kwargs = model.generate_custom_voice.call_args.kwargs
    assert kwargs["speaker"] == "Ryan"
    assert kwargs["instruct"] == "Calm pace."
    model.generate_voice_design.assert_not_called()
