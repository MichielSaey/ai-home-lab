import json
from pathlib import Path

from text2audiobook import formats  # noqa: F401
from text2audiobook.chunking import TextChunk
from text2audiobook.cli import main
from text2audiobook.config import load_config
from text2audiobook.pipeline import process_source
from text2audiobook.stems import BookStems, canonical_stages
from text2audiobook.tracking import RunTracker

_BODY = " ".join(f"word{i}" for i in range(40))


def _write_book(tmp_path: Path) -> tuple[Path, object]:
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
                "llm": {"cleanup": False},
                "output": {"skip_existing": False, "keep_wav": True, "loudnorm": False},
            }
        ),
        encoding="utf-8",
    )
    return source, load_config(config_path)


def test_canonical_stages_orders_and_rejects() -> None:
    assert canonical_stages(["speak", "extract"]) == ("extract", "speak")
    try:
        canonical_stages(["clean"])
    except ValueError as exc:
        assert "clean" in str(exc)
    else:
        raise AssertionError("expected unknown stage to fail")


def test_list_voices_exits_without_gpu() -> None:
    assert main(["--list-voices"]) == 0


def test_extract_format_speak_stems(tmp_path: Path, monkeypatch) -> None:
    source, config = _write_book(tmp_path)
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())

    def fake_synth(_kokoro, _text, wav_path, **_kwargs) -> None:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"RIFF")

    def fake_units(chapters, **_kwargs):
        chapter = chapters[0]
        return [
            TextChunk(
                chapter_index=chapter.index,
                chapter_title=chapter.title,
                chapter_slug=chapter.slug,
                chunk_index=0,
                text="hello",
            )
        ]

    monkeypatch.setattr(
        "text2audiobook.pipeline.load_llm",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("llm")),
    )
    monkeypatch.setattr("text2audiobook.pipeline.load_kokoro", lambda *_a, **_k: object())
    monkeypatch.setattr("text2audiobook.pipeline.unload_kokoro", lambda *_a, **_k: None)
    monkeypatch.setattr("text2audiobook.pipeline.synthesize_to_wav", fake_synth)
    monkeypatch.setattr(
        "text2audiobook.pipeline.build_m4b",
        lambda output_path, *_a, **_k: Path(output_path).write_bytes(b"m4b"),
    )
    monkeypatch.setattr("text2audiobook.pipeline.build_speak_units", fake_units)

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
    assert not stems.format_manifest.exists()

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
        voice="bf_emma",
    )
    assert llm_calls["n"] == 0
    assert stems.speak_manifest.exists()
    speak = json.loads(stems.speak_manifest.read_text(encoding="utf-8"))
    assert speak["voice"] == "bf_emma"
    assert speak["lang"] == "b"
    assert (config.paths.output_dir / f"{staging.name}.m4b").exists()
