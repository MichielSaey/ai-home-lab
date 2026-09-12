"""Unit tests for Base / VoiceDesign / CustomVoice TTS helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from text2audiobook.config import DEFAULT_TTS_INSTRUCT
from text2audiobook.tts import (
    compose_instruct,
    create_voice_clone_prompt,
    is_base,
    is_custom_voice,
    is_voice_design,
    iter_speak_batches,
    supports_instruct,
    synthesize_batch_to_wavs,
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


def test_is_base() -> None:
    assert is_base("Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    assert is_base("Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    assert not is_base("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    assert not is_base("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    assert not is_base(None)


def test_supports_instruct() -> None:
    assert supports_instruct("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    assert supports_instruct("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
    assert not supports_instruct("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    assert not supports_instruct("Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    assert not supports_instruct(None)


def test_synthesize_routes_to_voice_design(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_voice_design.return_value = ([np.zeros(8, dtype=np.float32)], 24000)
    model.generate_custom_voice.side_effect = AssertionError("should not call CustomVoice")
    model.generate_voice_clone.side_effect = AssertionError("should not call Base")

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
    assert kwargs["text"] == ["Hello world."]
    assert kwargs["language"] == ["English"]
    assert kwargs["instruct"] == ["Native English female narrator."]
    assert "speaker" not in kwargs
    model.generate_custom_voice.assert_not_called()
    model.generate_voice_clone.assert_not_called()
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
        model.generate_voice_design.call_args.kwargs["instruct"]
        == [DEFAULT_TTS_INSTRUCT]
    )


def test_synthesize_routes_to_custom_voice(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_custom_voice.return_value = ([np.zeros(8, dtype=np.float32)], 24000)
    model.generate_voice_design.side_effect = AssertionError("should not call VoiceDesign")
    model.generate_voice_clone.side_effect = AssertionError("should not call Base")

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
    assert kwargs["instruct"] == ["Calm pace."]
    model.generate_voice_design.assert_not_called()
    model.generate_voice_clone.assert_not_called()


def test_synthesize_06b_omits_instruct(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_custom_voice.return_value = ([np.zeros(8, dtype=np.float32)], 24000)

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    synthesize_to_wav(
        model,
        "Hello.",
        tmp_path / "cv06.wav",
        voice="Serena",
        language="English",
        instruct="Should be ignored on 0.6B.",
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    )
    kwargs = model.generate_custom_voice.call_args.kwargs
    assert kwargs["speaker"] == "Serena"
    assert "instruct" not in kwargs


def test_synthesize_routes_to_voice_clone_with_prompt(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_voice_clone.return_value = ([np.zeros(8, dtype=np.float32)], 24000)
    model.generate_custom_voice.side_effect = AssertionError("should not call CustomVoice")
    model.generate_voice_design.side_effect = AssertionError("should not call VoiceDesign")
    prompt = object()

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    synthesize_to_wav(
        model,
        "Hello clone.",
        tmp_path / "clone.wav",
        voice="cloned",
        language="English",
        instruct="ignored on Base",
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        voice_clone_prompt=prompt,
    )
    model.generate_voice_clone.assert_called_once()
    kwargs = model.generate_voice_clone.call_args.kwargs
    assert kwargs["text"] == ["Hello clone."]
    assert kwargs["language"] == ["English"]
    assert kwargs["voice_clone_prompt"] is prompt
    assert "speaker" not in kwargs
    assert "instruct" not in kwargs
    model.generate_custom_voice.assert_not_called()
    model.generate_voice_design.assert_not_called()


def test_synthesize_routes_to_voice_clone_with_ref(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_voice_clone.return_value = ([np.zeros(8, dtype=np.float32)], 24000)
    model.generate_custom_voice.side_effect = AssertionError("should not call CustomVoice")
    model.generate_voice_design.side_effect = AssertionError("should not call VoiceDesign")
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    synthesize_to_wav(
        model,
        "Hello clone.",
        tmp_path / "clone2.wav",
        voice="cloned",
        language="English",
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        ref_audio=ref,
        ref_text="Reference transcript.",
        x_vector_only=False,
    )
    kwargs = model.generate_voice_clone.call_args.kwargs
    assert kwargs["ref_audio"] == str(ref)
    assert kwargs["ref_text"] == "Reference transcript."
    assert kwargs["x_vector_only_mode"] is False
    assert "voice_clone_prompt" not in kwargs
    model.generate_custom_voice.assert_not_called()
    model.generate_voice_design.assert_not_called()


def test_iter_speak_batches_packing_boundaries() -> None:
    class Unit:
        def __init__(self, text: str, label: str) -> None:
            self.text = text
            self.label = label

    def _labels(batches: list) -> list[list[str]]:
        return [[u.label for u in batch] for batch in batches]

    def _assert_each_unit_once(source: list, batches: list) -> None:
        seen = [u.label for batch in batches for u in batch]
        assert len(seen) == len(source)
        assert sorted(seen) == sorted(u.label for u in source)

    units = [
        Unit("aa", "a"),
        Unit("bbb", "b"),
        Unit("c", "c"),
        Unit("dddddddd", "d"),  # oversized alone
        Unit("ee", "e"),
        Unit("ff", "f"),
    ]
    batches = list(iter_speak_batches(units, max_chars=5, max_items=3))
    # First-fit: after [a,b], residual pulls e/f past oversized d.
    assert _labels(batches) == [
        ["a", "b"],  # 2+3=5
        ["c", "e", "f"],  # 1 + residual 2+2; d skipped until alone
        ["d"],  # oversized alone
    ]
    _assert_each_unit_once(units, batches)

    by_items = list(iter_speak_batches(units[:4], max_chars=0, max_items=2))
    assert _labels(by_items) == [
        ["a", "b"],
        ["c", "d"],
    ]
    _assert_each_unit_once(units[:4], by_items)

    unlimited = list(iter_speak_batches(units[:3], max_chars=0, max_items=0))
    assert _labels(unlimited) == [["a", "b", "c"]]
    _assert_each_unit_once(units[:3], unlimited)

    # Residual fill: after first 3, remaining 1 pulls the trailing 1-char unit.
    residual_units = [
        Unit("xxx", "x1"),
        Unit("yyy", "y2"),
        Unit("zzz", "z3"),
        Unit("w", "w4"),
    ]
    residual = list(iter_speak_batches(residual_units, max_chars=4, max_items=8))
    assert _labels(residual) == [
        ["x1", "w4"],  # 3+1; skips later 3s that do not fit rem=1
        ["y2"],
        ["z3"],
    ]
    _assert_each_unit_once(residual_units, residual)


def test_synthesize_batch_voice_clone_writes_each_wav(tmp_path: Path, monkeypatch) -> None:
    model = MagicMock()
    model.generate_voice_clone.return_value = (
        [
            np.zeros(4, dtype=np.float32),
            np.zeros(5, dtype=np.float32),
            np.zeros(6, dtype=np.float32),
        ],
        24000,
    )
    prompt = object()
    written: list[Path] = []

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")
        written.append(Path(path))

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    paths = [tmp_path / f"{i}.wav" for i in range(3)]
    synthesize_batch_to_wavs(
        model,
        [("one", paths[0]), ("two", paths[1]), ("three", paths[2])],
        voice="cloned",
        language="English",
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        voice_clone_prompt=prompt,
    )
    model.generate_voice_clone.assert_called_once()
    kwargs = model.generate_voice_clone.call_args.kwargs
    assert kwargs["text"] == ["one", "two", "three"]
    assert kwargs["language"] == ["English", "English", "English"]
    assert kwargs["voice_clone_prompt"] is prompt
    for path in paths:
        assert path.exists()


def test_synthesize_batch_raises_on_wav_count_mismatch(tmp_path: Path) -> None:
    model = MagicMock()
    model.generate_voice_clone.return_value = ([np.zeros(4, dtype=np.float32)], 24000)
    try:
        synthesize_batch_to_wavs(
            model,
            [("a", tmp_path / "a.wav"), ("b", tmp_path / "b.wav")],
            voice="cloned",
            language="English",
            model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            voice_clone_prompt=object(),
        )
    except RuntimeError as exc:
        assert "returned 1 wav(s) for 2 text(s)" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_synthesize_batch_oom_splits_and_retries(tmp_path: Path, monkeypatch) -> None:
    """CUDA OOM on a large batch should empty cache, split halves, and write all WAVs."""
    model = MagicMock()
    prompt = object()
    call_sizes: list[int] = []

    def generate_side_effect(**kwargs):
        texts = kwargs["text"]
        size = len(texts)
        call_sizes.append(size)
        if size >= 3:
            raise RuntimeError("CUDA out of memory")
        return (
            [np.zeros(4 + i, dtype=np.float32) for i in range(size)],
            24000,
        )

    model.generate_voice_clone.side_effect = generate_side_effect

    def fake_write(path, *_a, **_k):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.tts.sf.write", fake_write)

    empty_cache = MagicMock()
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = True
    fake_torch.cuda.empty_cache = empty_cache
    # Not an OutOfMemoryError subclass — exercise the RuntimeError/"out of memory" path.
    fake_torch.cuda.OutOfMemoryError = type("OutOfMemoryError", (RuntimeError,), {})
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)

    paths = [tmp_path / f"{i}.wav" for i in range(4)]
    synthesize_batch_to_wavs(
        model,
        [(f"t{i}", paths[i]) for i in range(4)],
        voice="cloned",
        language="English",
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        voice_clone_prompt=prompt,
    )

    assert call_sizes[0] == 4
    assert all(size < 3 for size in call_sizes[1:])
    assert sum(call_sizes[1:]) == 4
    empty_cache.assert_called()
    for path in paths:
        assert path.exists()


def test_synthesize_batch_oom_on_single_item_reraises(
    tmp_path: Path, monkeypatch
) -> None:
    model = MagicMock()
    model.generate_voice_clone.side_effect = RuntimeError("CUDA out of memory")

    empty_cache = MagicMock()
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = True
    fake_torch.cuda.empty_cache = empty_cache
    fake_torch.cuda.OutOfMemoryError = type("OutOfMemoryError", (RuntimeError,), {})
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)

    try:
        synthesize_batch_to_wavs(
            model,
            [("only", tmp_path / "only.wav")],
            voice="cloned",
            language="English",
            model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            voice_clone_prompt=object(),
        )
    except RuntimeError as exc:
        assert "out of memory" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError")
    empty_cache.assert_called_once()


def test_create_voice_clone_prompt_passes_x_vector_only_mode() -> None:
    model = MagicMock()
    model.create_voice_clone_prompt.return_value = ["prompt"]
    result = create_voice_clone_prompt(
        model,
        ref_audio=Path("/tmp/ref.wav"),
        ref_text="Hi.",
        x_vector_only=True,
    )
    assert result == ["prompt"]
    kwargs = model.create_voice_clone_prompt.call_args.kwargs
    assert kwargs["ref_audio"] == "/tmp/ref.wav"
    assert kwargs["ref_text"] == "Hi."
    assert kwargs["x_vector_only_mode"] is True
