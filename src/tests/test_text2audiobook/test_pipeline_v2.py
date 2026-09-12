import json
from dataclasses import replace
from pathlib import Path

from text2audiobook import formats  # noqa: F401
from text2audiobook.chunking import TextChunk
from text2audiobook.cli import main
from text2audiobook.config import load_config
from text2audiobook.pipeline import process_source
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

    def fake_synth(_model, _text, wav_path, **_kwargs) -> None:
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
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_to_wav", fake_synth)
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


def test_speak_only_rejects_stale_format_stem(tmp_path: Path, monkeypatch) -> None:
    source, config = _write_book(tmp_path)
    stems = _stems_after_extract_format(source, config, monkeypatch)
    # Make format fingerprint stale while leaving chunk files on disk.
    manifest = json.loads(stems.format_manifest.read_text(encoding="utf-8"))
    manifest["clean_hash"] = "stale"
    stems.format_manifest.write_text(json.dumps(manifest), encoding="utf-8")

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
        assert "stale" in str(exc).lower() or "format" in str(exc).lower()
    else:
        raise AssertionError("speak-only should reject a stale format stem")


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

    def fake_synth(_model, text, wav_path, **_kwargs) -> None:
        synth_calls.append(text)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", _forbid_llm)
    monkeypatch.setattr("text2audiobook.pipeline.iter_clean_chunks_batched", fake_clean)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_to_wav", fake_synth)
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

    def fake_synth(_model, text, wav_path, **_kwargs) -> None:
        synth_calls.append(text)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", _forbid_llm)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_to_wav", fake_synth)
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

    def fake_synth(_model, text, wav_path, **kwargs) -> None:
        synth_instructs.append(kwargs.get("instruct"))
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_llm", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.iter_clean_chunks_batched", fake_clean)
    monkeypatch.setattr("text2audiobook.pipeline.apply_direction_pass", fake_direction)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_to_wav", fake_synth)
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

    def fake_synth(_model, text, wav_path, **kwargs) -> None:
        synth_instructs.append(kwargs.get("instruct"))
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"RIFF")

    monkeypatch.setattr("text2audiobook.pipeline.load_llm", _forbid_llm)
    monkeypatch.setattr("text2audiobook.pipeline.load_tts", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_tts", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_to_wav", fake_synth)
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
