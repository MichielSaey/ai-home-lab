import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from text2audiobook import formats  # noqa: F401
from text2audiobook.chunking import TextChunk
from text2audiobook.cli import main
from text2audiobook.config import load_config
from text2audiobook.io import BookMetadata
from text2audiobook.logging_setup import ProgressContext
from text2audiobook.pipeline import _synthesize_and_encode, process_source
from text2audiobook.stems import BookStems, canonical_stages, load_jsonl
from text2audiobook.tracking import RunTracker

_BODY = " ".join(f"word{i}" for i in range(40))


def _write_book(tmp_path: Path, *, skip_existing: bool = False) -> tuple[Path, object]:
    source = tmp_path / "input" / "sample.md"
    source.parent.mkdir(parents=True)
    source.write_text(f"# Chapter One\n\n{_BODY}\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "paths": {
                    "input_dir": "input",
                    "staging_dir": "staging",
                    "output_dir": "output",
                    "runs_dir": "runs",
                },
                "selection": {"keep_chapter_indices": [0]},
                "llm": {"cleanup": False, "direction": False},
                "output": {
                    "skip_existing": skip_existing,
                    "keep_wav": True,
                    "loudnorm": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return source, load_config(config_path)


def _forbid_llm(*_a, **_k):
    raise AssertionError("llm")


def _stems_after_extract_format(source: Path, config, monkeypatch) -> BookStems:
    monkeypatch.setattr("text2audiobook.pipeline.load_llm", _forbid_llm)
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("extract", "clean", "format"),
        tts_device="cpu",
    )
    staging = next(p for p in config.paths.staging_dir.iterdir() if p.is_dir())
    return BookStems(staging)


def test_canonical_stages_orders_and_rejects() -> None:
    assert canonical_stages(["speak", "extract"]) == ("extract", "speak")
    assert canonical_stages(["format", "clean"]) == ("clean", "format")
    try:
        canonical_stages(["nope"])
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected unknown stage to fail")


def test_list_voices_exits_without_gpu() -> None:
    assert main(["--list-voices"]) == 0


def test_extract_format_speak_stems(tmp_path: Path, monkeypatch) -> None:
    source, config = _write_book(tmp_path)
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())

    def fake_synth(_model, items, **_kwargs) -> None:
        for _text, wav_path in items:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFF")

    def fake_units(format_units, **_kwargs):
        unit = format_units[0]
        return [
            TextChunk(
                chapter_index=unit.chapter_index,
                chapter_title=unit.chapter_title,
                chapter_slug=unit.chapter_slug,
                chunk_index=0,
                text="hello",
            )
        ]

    monkeypatch.setattr(
        "text2audiobook.pipeline.load_llm",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("llm")),
    )
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    monkeypatch.setattr("text2audiobook.pipeline.build_speak_units_from_chunks", fake_units)

    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("extract",),
        tts_device="cpu",
    )
    staging = next(p for p in config.paths.staging_dir.iterdir() if p.is_dir())
    stems = BookStems(staging)
    assert stems.chapters_json.exists()
    extract_manifest = json.loads(stems.extract_manifest.read_text(encoding="utf-8"))
    assert extract_manifest.get("parsed_hash")
    assert not stems.format_manifest.exists()

    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("clean",),
        tts_device="cpu",
    )
    assert stems.clean_sections_jsonl.exists()
    assert stems.clean_manifest.exists()

    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("format",),
        tts_device="cpu",
    )
    assert stems.format_manifest.exists()
    scripts = list(stems.format_chapter_dir.glob("*.txt"))
    assert scripts

    llm_calls = {"n": 0}

    def forbid_llm(*_a, **_k):
        llm_calls["n"] += 1
        raise AssertionError("speak must not load Qwen")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", forbid_llm)
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
    )
    assert llm_calls["n"] == 0
    assert stems.speak_manifest.exists()
    speak = json.loads(stems.speak_manifest.read_text(encoding="utf-8"))
    assert speak["voice"] == "Serena"
    assert speak["lang"] == "English"
    assert speak["model_id"] == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert "instruct" not in speak
    assert (config.paths.output_dir / f"{staging.name}.m4b").exists()


def test_speak_only_uses_stale_format_stem(tmp_path: Path, monkeypatch) -> None:
    source, config = _write_book(tmp_path)
    stems = _stems_after_extract_format(source, config, monkeypatch)
    # Make format fingerprint stale while leaving chunk files on disk.
    manifest = json.loads(stems.format_manifest.read_text(encoding="utf-8"))
    manifest["clean_hash"] = "stale"
    stems.format_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    def fake_synth(_model, items, **_kwargs) -> None:
        for _text, wav_path in items:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
    )
    assert stems.speak_manifest.exists()
    assert (config.paths.output_dir / f"{stems.root.name}.m4b").exists()


def test_speak_resumes_existing_wavs_without_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """Interrupted speak (no speak manifest yet) should skip matching WAVs."""
    source, config = _write_book(tmp_path, skip_existing=True)
    stems = _stems_after_extract_format(source, config, monkeypatch)
    synth_calls = {"n": 0}

    def fake_synth(_model, items, **_kwargs) -> None:
        synth_calls["n"] += 1
        for _text, wav_path in items:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
    )
    assert synth_calls["n"] >= 1
    first_calls = synth_calls["n"]
    # Simulate interrupt before manifest write: keep WAVs + units, drop manifest.
    assert stems.speak_units_jsonl.exists()
    assert any(stems.speak_wav_dir.rglob("*.wav"))
    stems.speak_manifest.unlink(missing_ok=True)

    synth_calls["n"] = 0
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
        force=False,
    )
    assert synth_calls["n"] == 0, (
        f"expected WAV resume without manifest; first run had {first_calls} synth batches"
    )


def test_speak_does_not_reuse_wavs_when_tts_fingerprint_changes(
    tmp_path: Path, monkeypatch
) -> None:
    source, config = _write_book(tmp_path, skip_existing=True)
    stems = _stems_after_extract_format(source, config, monkeypatch)
    synth_calls = {"n": 0}

    def fake_synth(_model, items, **_kwargs) -> None:
        synth_calls["n"] += 1
        for _text, wav_path in items:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
    )
    assert synth_calls["n"] >= 1
    assert any(stems.speak_wav_dir.rglob("*.wav"))

    synth_calls["n"] = 0
    config = replace(config, tts=replace(config.tts, voice="Aiden"))
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
        force=False,
    )
    assert synth_calls["n"] >= 1, "TTS fingerprint change must not reuse old WAVs"


def test_speak_only_rejects_missing_format_stem(tmp_path: Path, monkeypatch) -> None:
    source, config = _write_book(tmp_path)
    stems = _stems_after_extract_format(source, config, monkeypatch)
    stems.format_chunks_jsonl.unlink()

    monkeypatch.setattr(
        "text2audiobook.pipeline.load_tts",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not load tts")),
    )
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    try:
        process_source(
            source,
            config,
            tracker=tracker,
            record=record,
            stages=("speak",),
            tts_device="cpu",
        )
    except FileNotFoundError as exc:
        assert "format" in str(exc).lower()
    else:
        raise AssertionError("speak-only should reject a missing format stem")


def test_customvoice_rejects_designed_voice(tmp_path: Path) -> None:
    from text2audiobook.pipeline import _resolve_tts

    _, config = _write_book(tmp_path)
    custom = replace(
        config,
        tts=replace(
            config.tts,
            model_id="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            voice="designed",
        ),
    )
    try:
        _resolve_tts(custom, voice=None, staging_root=tmp_path / "staging")
    except ValueError as exc:
        assert "designed" in str(exc).lower() or "CustomVoice" in str(exc)
    else:
        raise AssertionError("CustomVoice + designed should raise before synthesis")

    try:
        _resolve_tts(
            replace(custom, tts=replace(custom.tts, voice="Ryan")),
            voice="designed",
            staging_root=tmp_path / "staging",
        )
    except ValueError as exc:
        assert "designed" in str(exc).lower() or "VoiceDesign" in str(exc)
    else:
        raise AssertionError("--voice designed with CustomVoice should raise")


def test_base_rejects_missing_ref_audio(tmp_path: Path) -> None:
    from text2audiobook.pipeline import _resolve_tts

    _, config = _write_book(tmp_path)
    base_missing = replace(
        config,
        tts=replace(
            config.tts,
            model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            voice="cloned",
            ref_audio=None,
            ref_text="Transcript.",
        ),
    )
    try:
        _resolve_tts(base_missing, voice=None, staging_root=tmp_path / "staging")
    except ValueError as exc:
        assert "ref_audio" in str(exc)
    else:
        raise AssertionError("Base without ref_audio should raise")

    missing_file = replace(
        base_missing,
        tts=replace(base_missing.tts, ref_audio=str(tmp_path / "nope.wav")),
    )
    try:
        _resolve_tts(missing_file, voice=None, staging_root=tmp_path / "staging")
    except ValueError as exc:
        assert "ref_audio" in str(exc) or "not found" in str(exc).lower()
    else:
        raise AssertionError("Base with missing ref_audio file should raise")

    no_text = replace(
        missing_file,
        tts=replace(
            missing_file.tts,
            ref_audio=str(tmp_path / "ref.wav"),
            ref_text="  ",
            x_vector_only=False,
        ),
    )
    (tmp_path / "ref.wav").write_bytes(b"RIFF")
    try:
        _resolve_tts(no_text, voice=None, staging_root=tmp_path / "staging")
    except ValueError as exc:
        assert "ref_text" in str(exc)
    else:
        raise AssertionError("Base without ref_text should raise when not x_vector_only")

    # Non-speak stages may resolve Base without the ref clip present yet.
    deferred = _resolve_tts(
        base_missing,
        voice=None,
        staging_root=tmp_path / "staging",
        validate_clone_ref=False,
    )
    assert deferred.voice == "cloned"
    assert deferred.model_id.endswith("-Base")


def test_base_speak_fingerprint_includes_ref_hash(tmp_path: Path) -> None:
    from text2audiobook.pipeline import _resolve_tts, _speak_fingerprint
    from text2audiobook.stems import file_sha256

    _, config = _write_book(tmp_path)
    ref = tmp_path / "ref_clone.wav"
    ref.write_bytes(b"RIFFCLONE")
    base_cfg = replace(
        config,
        tts=replace(
            config.tts,
            model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            voice="cloned",
            ref_audio=str(ref),
            ref_text="Reference transcript.",
            x_vector_only=False,
            instruct="should be omitted from fingerprint",
        ),
    )
    tts = _resolve_tts(base_cfg, voice=None, staging_root=tmp_path / "staging")
    assert tts.voice == "cloned"
    fp = _speak_fingerprint(base_cfg, tts, format_hash="abc")
    assert fp["model_id"] == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert fp["voice"] == "cloned"
    assert fp["ref_audio_sha256"] == file_sha256(ref)
    assert fp["ref_text"] == "Reference transcript."
    assert fp["x_vector_only"] is False
    assert "instruct" not in fp


def test_format_invalidates_when_extract_chapters_change(tmp_path: Path, monkeypatch) -> None:
    source, config = _write_book(tmp_path)
    stems = _stems_after_extract_format(source, config, monkeypatch)
    payload = json.loads(stems.chapters_json.read_text(encoding="utf-8"))
    payload[0]["text"] = "Meet on 03/09/2026. " + _BODY
    stems.chapters_json.write_text(json.dumps(payload), encoding="utf-8")

    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("clean", "format"),
        force=True,
        tts_device="cpu",
    )
    script = next(stems.format_chapter_dir.glob("*.txt")).read_text(encoding="utf-8")
    assert "the third of September, twenty twenty-six" in script


def test_stale_format_cache_is_dropped_when_prompt_changes(
    tmp_path: Path, monkeypatch
) -> None:
    source, config = _write_book(tmp_path, skip_existing=True)
    stems = _stems_after_extract_format(source, config, monkeypatch)
    rows = load_jsonl(stems.format_chunks_jsonl)
    assert rows
    rows[0]["cleaned_text"] = "POISON"
    stems.format_chunks_jsonl.write_text(
        json.dumps(rows[0], ensure_ascii=False) + "\n", encoding="utf-8"
    )

    config = replace(
        config, llm=replace(config.llm, clean_prompt="Different prompt.\n\nText:\n{text}")
    )
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("format",),
        tts_device="cpu",
    )
    script = next(stems.format_chapter_dir.glob("*.txt")).read_text(encoding="utf-8")
    assert "POISON" not in script


def test_force_format_with_new_script_invalidates_speak_wavs(
    tmp_path: Path, monkeypatch
) -> None:
    from text2audiobook.llm import CleanedChunk

    source, config = _write_book(tmp_path, skip_existing=True)
    texts = iter(["first pass script", "second pass script"])

    def fake_clean(llm, chunks, llm_config, **_kwargs):
        text = next(texts)
        for chunk in chunks:
            yield CleanedChunk(
                chapter_index=chunk.chapter_index,
                chapter_title=chunk.chapter_title,
                chapter_slug=chunk.chapter_slug,
                chunk_index=chunk.chunk_index,
                raw_text=chunk.text,
                cleaned_text=text,
            )

    synth_calls: list[str] = []

    def fake_synth(_model, items, **_kwargs) -> None:
        for text, wav_path in items:
            synth_calls.append(text)
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", _forbid_llm)
    monkeypatch.setattr("text2audiobook.pipeline.iter_clean_chunks_batched", fake_clean)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_speak_units_from_chunks",
        lambda format_units, **_kwargs: [
            TextChunk(
                chapter_index=format_units[0].chapter_index,
                chapter_title=format_units[0].chapter_title,
                chapter_slug=format_units[0].chapter_slug,
                chunk_index=0,
                text=format_units[0].text,
            )
        ],
    )

    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("extract", "clean", "format", "speak"),
        tts_device="cpu",
    )
    assert synth_calls == ["first pass script"]

    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("format",),
        force=True,
        tts_device="cpu",
    )
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
    )
    assert synth_calls == ["first pass script", "second pass script"]


def test_edited_format_unit_resynthesizes(tmp_path: Path, monkeypatch) -> None:
    source, config = _write_book(tmp_path, skip_existing=True)
    synth_calls: list[str] = []

    def fake_synth(_model, items, **_kwargs) -> None:
        for text, wav_path in items:
            synth_calls.append(text)
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", _forbid_llm)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_speak_units_from_chunks",
        lambda format_units, **_kwargs: [
            TextChunk(
                chapter_index=format_units[0].chapter_index,
                chapter_title=format_units[0].chapter_title,
                chapter_slug=format_units[0].chapter_slug,
                chunk_index=0,
                text=format_units[0].text,
            )
        ],
    )

    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("extract", "clean", "format", "speak"),
        tts_device="cpu",
    )
    assert synth_calls
    stems = BookStems(next(p for p in config.paths.staging_dir.iterdir() if p.is_dir()))
    rows = load_jsonl(stems.format_chunks_jsonl)
    rows[0]["cleaned_text"] = "manually edited format unit"
    stems.format_chunks_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("speak",),
        tts_device="cpu",
    )
    assert synth_calls[-1] == "manually edited format unit"


def test_direction_pass_writes_instruct_and_speak_uses_it(
    tmp_path: Path, monkeypatch
) -> None:
    from text2audiobook.llm import CleanedChunk

    source, config = _write_book(tmp_path)
    config = replace(
        config,
        llm=replace(config.llm, cleanup=False, direction=True),
        tts=replace(config.tts, instruct="GLOBAL BASELINE INSTRUCT"),
    )

    def fake_clean(llm, chunks, llm_config, **_kwargs):
        for chunk in chunks:
            yield CleanedChunk(
                chapter_index=chunk.chapter_index,
                chapter_title=chunk.chapter_title,
                chapter_slug=chunk.chapter_slug,
                chunk_index=chunk.chunk_index,
                raw_text=chunk.text,
                cleaned_text=chunk.text,
                instruct=None,
            )

    def fake_direction(llm, chunks, llm_config, **_kwargs):
        return [
            replace(chunk, instruct="CHUNK LOCAL: calm steady exposition")
            for chunk in chunks
        ]

    synth_instructs: list[str | None] = []

    def fake_synth(_model, items, **kwargs) -> None:
        instruct = kwargs.get("instruct")
        if isinstance(instruct, (list, tuple)):
            for value, (_text, wav_path) in zip(instruct, items, strict=True):
                synth_instructs.append(value)
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                wav_path.write_bytes(b"RIFF")
        else:
            for _text, wav_path in items:
                synth_instructs.append(instruct)
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_llm", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.iter_clean_chunks_batched", fake_clean)
    monkeypatch.setattr("text2audiobook.pipeline.apply_direction_pass", fake_direction)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_speak_units_from_chunks",
        lambda format_units, **_kwargs: [
            TextChunk(
                chapter_index=format_units[0].chapter_index,
                chapter_title=format_units[0].chapter_title,
                chapter_slug=format_units[0].chapter_slug,
                chunk_index=0,
                text=format_units[0].text,
                instruct=format_units[0].instruct,
            )
        ],
    )

    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("extract", "clean", "format", "speak"),
        tts_device="cpu",
    )
    stems = BookStems(next(p for p in config.paths.staging_dir.iterdir() if p.is_dir()))
    rows = load_jsonl(stems.format_chunks_jsonl)
    assert rows
    assert rows[0]["instruct"] == "CHUNK LOCAL: calm steady exposition"
    speak_rows = load_jsonl(stems.speak_units_jsonl)
    assert speak_rows[0]["instruct"] == "CHUNK LOCAL: calm steady exposition"
    assert synth_instructs == [
        "GLOBAL BASELINE INSTRUCT CHUNK LOCAL: calm steady exposition"
    ]


def test_direction_disabled_speak_falls_back_to_global_instruct(
    tmp_path: Path, monkeypatch
) -> None:
    source, config = _write_book(tmp_path)
    config = replace(
        config,
        llm=replace(config.llm, cleanup=False, direction=False),
        tts=replace(config.tts, instruct="GLOBAL BASELINE INSTRUCT"),
    )

    synth_instructs: list[str | None] = []

    def fake_synth(_model, items, **kwargs) -> None:
        instruct = kwargs.get("instruct")
        if isinstance(instruct, (list, tuple)):
            for value, (_text, wav_path) in zip(instruct, items, strict=True):
                synth_instructs.append(value)
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                wav_path.write_bytes(b"RIFF")
        else:
            for _text, wav_path in items:
                synth_instructs.append(instruct)
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", _forbid_llm)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_speak_units_from_chunks",
        lambda format_units, **_kwargs: [
            TextChunk(
                chapter_index=format_units[0].chapter_index,
                chapter_title=format_units[0].chapter_title,
                chapter_slug=format_units[0].chapter_slug,
                chunk_index=0,
                text=format_units[0].text,
                instruct=format_units[0].instruct,
            )
        ],
    )

    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(source)
    process_source(
        source,
        config,
        tracker=tracker,
        record=record,
        stages=("extract", "clean", "format", "speak"),
        tts_device="cpu",
    )
    stems = BookStems(next(p for p in config.paths.staging_dir.iterdir() if p.is_dir()))
    rows = load_jsonl(stems.format_chunks_jsonl)
    assert rows[0].get("instruct") is None
    assert synth_instructs == ["GLOBAL BASELINE INSTRUCT"]


def test_speak_progress_unit_done_monotonic_when_packing_reorders(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """Length-sorted batch packing reorders units; unit_done must still rise."""
    staging = tmp_path / "staging" / "book"
    speak_wav = staging / "speak" / "wav"
    speak_wav.mkdir(parents=True)
    (tmp_path / "runs").mkdir()

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "paths": {
                    "input_dir": "input",
                    "staging_dir": "staging",
                    "output_dir": "output",
                    "runs_dir": "runs",
                },
                "tts": {
                    "batch_max_chars": 0,
                    "batch_max_pad_chars": 0,
                    "batch_max_items": 1,
                },
                "output": {"chapter_mp3": False, "loudnorm": False},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)
    tts_config = replace(config.tts)

    # Book order: long, short, medium → packing (longest first) synthesizes long→medium→short.
    units = [
        TextChunk(0, "Ch A", "ch_a", 0, "x" * 30),
        TextChunk(0, "Ch A", "ch_a", 1, "y" * 5),
        TextChunk(1, "Ch B", "ch_b", 0, "z" * 15),
    ]

    synth_order: list[str] = []

    def fake_synth(_model, items, **_kwargs) -> None:
        for text, wav_path in items:
            synth_order.append(text)
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.synthesize_batch_to_wavs", fake_synth)

    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    record = tracker.start_book(tmp_path / "input" / "sample.md")
    metadata = BookMetadata(
        title="Book",
        author="Author",
        language="en",
        cover_bytes=None,
        slug="book",
        staging_dir=staging,
        m4b_path=tmp_path / "output" / "book.m4b",
    )
    stems = BookStems(staging)
    progress = ProgressContext(book_title="Book")

    with (
        ThreadPoolExecutor(max_workers=1) as executor,
        caplog.at_level(logging.INFO, logger="text2audiobook.pipeline"),
    ):
        _synthesize_and_encode(
            units,
            tts_model=object(),
            config=config,
            tts_config=tts_config,
            metadata=metadata,
            stems=stems,
            tracker=tracker,
            record=record,
            executor=executor,
            progress=progress,
            skip_wavs=False,
        )

    assert synth_order == ["x" * 30, "z" * 15, "y" * 5]
    unit_dones = [
        int(match.group(1))
        for record in caplog.records
        if (match := re.search(r"unit=(\d+)/3", record.getMessage()))
    ]
    assert unit_dones == [1, 2, 3]
    assert unit_dones == sorted(unit_dones)
