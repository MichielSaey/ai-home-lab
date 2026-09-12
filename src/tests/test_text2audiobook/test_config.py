import json
from pathlib import Path

from text2audiobook.config import (
    deep_merge,
    load_config,
    resolve_book_config,
)


def test_load_config_resolves_new_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "paths": {
                    "input_dir": "books",
                    "staging_dir": "scratch",
                    "output_dir": "out",
                    "runs_dir": "runs",
                },
                "output": {"chapter_mp3": False},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.paths.input_dir == tmp_path / "books"
    assert cfg.paths.staging_dir == tmp_path / "scratch"
    assert cfg.paths.output_dir == tmp_path / "out"
    assert cfg.output.chapter_mp3 is False
    assert cfg.output.speak_footnote_cues is False


def test_load_config_maps_legacy_words_per_chunk(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"chunking": {"words_per_chunk": 800}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.chunking.format_words_per_chunk == 800
    assert cfg.chunking.speak_target_chars == 800


def test_load_config_maps_legacy_phoneme_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "chunking": {
                    "speak_target_phonemes": 160,
                    "speak_max_phonemes": 400,
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.chunking.speak_target_chars == 800
    assert cfg.chunking.speak_max_chars == 1200


def test_load_config_ignores_legacy_tts_speed(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tts": {"voice": "Ryan", "speed": 0.9}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.tts.voice == "Ryan"
    assert not hasattr(cfg.tts, "speed")


def test_load_config_maps_legacy_kokoro_lang_codes(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tts": {"lang": "a", "voice": "Ryan"}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.tts.lang == "English"

    config_path.write_text(
        json.dumps({"tts": {"lang": "z", "voice": "Vivian"}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.tts.lang == "Chinese"

    config_path.write_text(
        json.dumps({"tts": {"lang": "h", "voice": "Ryan"}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.tts.lang == "English"


def test_load_config_maps_legacy_kokoro_voices(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tts": {"lang": "a", "voice": "af_bella"}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.tts.voice == "Serena"
    assert cfg.tts.lang == "English"

    config_path.write_text(
        json.dumps({"tts": {"voice": "bm_george"}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.tts.voice == "Ryan"


def test_load_config_accepts_epub_dir_alias(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"paths": {"epub_dir": "legacy-books"}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.paths.input_dir == tmp_path / "legacy-books"


def test_deep_merge_overlay_wins() -> None:
    merged = deep_merge(
        {"a": 1, "nested": {"x": 1, "y": 2}},
        {"nested": {"y": 9}, "b": 3},
    )
    assert merged == {"a": 1, "nested": {"x": 1, "y": 9}, "b": 3}


def test_resolve_book_config_merges_overlay(tmp_path: Path) -> None:
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
                "chunking": {"format_words_per_chunk": 1000},
                "output": {"speak_footnote_cues": False},
            }
        ),
        encoding="utf-8",
    )
    books = tmp_path / "config.books"
    books.mkdir()
    (books / "cute_accelerationism.json").write_text(
        json.dumps(
            {
                "paths": {"input_dir": "ignored"},
                "chunking": {"format_words_per_chunk": 700},
                "output": {"speak_footnote_cues": True},
            }
        ),
        encoding="utf-8",
    )
    base = load_config(config_path)
    resolved = resolve_book_config(base, "cute_accelerationism")
    assert resolved.chunking.format_words_per_chunk == 700
    assert resolved.output.speak_footnote_cues is True
    assert resolved.paths.input_dir == tmp_path / "input"


def test_load_config_defaults_direction_and_customvoice(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    cfg = load_config(config_path)
    assert cfg.tts.voice == "Serena"
    assert cfg.tts.model_id == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert cfg.tts.lang == "English"
    assert cfg.tts.ref_audio is None
    assert cfg.tts.ref_text is None
    assert cfg.tts.x_vector_only is False
    assert cfg.tts.instruct is not None
    assert "warm" in cfg.tts.instruct.lower()
    assert "native" in cfg.tts.instruct.lower()
    assert "chinese" in cfg.tts.instruct.lower() or "mandarin" in cfg.tts.instruct.lower()
    assert cfg.tts.batch_max_chars == 2800
    assert cfg.tts.batch_max_items == 4
    assert cfg.chunking.speak_target_chars == 800
    assert cfg.chunking.speak_max_chars == 1200
    assert cfg.llm.direction is True
    assert "{text}" in cfg.llm.direction_prompt
    assert "bracket" in cfg.llm.direction_prompt.lower()
    assert "accent" in cfg.llm.direction_prompt.lower()
    assert cfg.llm.direction_max_new_tokens == 128


def test_load_config_resolves_ref_audio(tmp_path: Path) -> None:
    from text2audiobook.config import resolve_ref_audio

    wav = tmp_path / "voices" / "ref.wav"
    wav.parent.mkdir()
    wav.write_bytes(b"RIFF")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tts": {
                    "model_id": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                    "voice": "cloned",
                    "ref_audio": "voices/ref.wav",
                    "ref_text": "Hello.",
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert Path(cfg.tts.ref_audio) == wav
    assert resolve_ref_audio("voices/ref.wav", config_path=config_path) == wav
    assert resolve_ref_audio(None, config_path=config_path) is None
    assert resolve_ref_audio(str(wav), config_path=config_path) == wav


def test_resolve_book_config_missing_keeps_default(tmp_path: Path) -> None:
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
                "chunking": {"format_words_per_chunk": 1000},
            }
        ),
        encoding="utf-8",
    )
    base = load_config(config_path)
    resolved = resolve_book_config(base, "unknown_book")
    assert resolved.chunking.format_words_per_chunk == 1000
    assert resolved is base
