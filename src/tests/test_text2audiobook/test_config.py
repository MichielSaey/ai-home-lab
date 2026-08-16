import json
from pathlib import Path

from epub2audiobook.config import DEFAULT_JELLYFIN_URL, load_config


def _write_config(tmp_path: Path, extra: dict | None = None) -> Path:
    payload = {
        "paths": {
            "epub_dir": "books",
            "staging_dir": "scratch",
            "output_dir": "out",
            "runs_dir": "runs",
        },
        "output": {"chapter_mp3": False},
    }
    if extra:
        payload.update(extra)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def test_load_config_resolves_new_paths(tmp_path: Path) -> None:
    cfg = load_config(_write_config(tmp_path))
    assert cfg.paths.epub_dir == tmp_path / "books"
    assert cfg.paths.staging_dir == tmp_path / "scratch"
    assert cfg.paths.output_dir == tmp_path / "out"
    assert cfg.output.chapter_mp3 is False
    assert cfg.publish.enabled is False
    assert cfg.publish.url == DEFAULT_JELLYFIN_URL


def test_publish_env_enables_rsync(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://192.168.0.10:8096/")
    monkeypatch.setenv("JELLYFIN_API_KEY", "secret")
    monkeypatch.setenv("JELLYFIN_RSYNC_TARGET", "casaos@192.168.0.10:/mnt/media/audiobooks")
    monkeypatch.setenv("JELLYFIN_CONTAINER_PATH", "/data/audiobooks")
    cfg = load_config(_write_config(tmp_path))
    assert cfg.publish.enabled is True
    assert cfg.publish.url == "http://192.168.0.10:8096"
    assert cfg.publish.api_key == "secret"
    assert cfg.publish.rsync_target == "casaos@192.168.0.10:/mnt/media/audiobooks"
    assert cfg.publish.container_path == "/data/audiobooks"
    snapshot = cfg.to_dict()
    assert snapshot["publish"]["api_key"] == "***"


def test_publish_env_can_disable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_PUBLISH", "0")
    monkeypatch.setenv("JELLYFIN_LIBRARY_ROOT", "/mnt/media/audiobooks")
    cfg = load_config(_write_config(tmp_path))
    assert cfg.publish.enabled is False
