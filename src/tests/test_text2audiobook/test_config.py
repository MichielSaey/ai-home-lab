import json
from pathlib import Path

from text2audiobook.config import load_config


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


def test_load_config_maps_legacy_words_per_chunk(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"chunking": {"words_per_chunk": 800}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.chunking.format_words_per_chunk == 800
    assert cfg.chunking.speak_target_phonemes == 160


def test_load_config_accepts_epub_dir_alias(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"paths": {"epub_dir": "legacy-books"}}),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.paths.input_dir == tmp_path / "legacy-books"
