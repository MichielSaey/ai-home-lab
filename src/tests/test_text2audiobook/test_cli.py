"""CLI stage-flag selection."""

import argparse

from text2audiobook.cli import _selected_stages, main
from text2audiobook.config import load_config


def _ns(**flags: bool) -> argparse.Namespace:
    base = {name: False for name in ("extract", "clean", "format", "speak")}
    base.update(flags)
    return argparse.Namespace(**base)


def test_selected_stages_defaults_to_full_pipeline() -> None:
    assert _selected_stages(_ns()) is None


def test_selected_stages_combinable_and_ordered() -> None:
    assert _selected_stages(_ns(speak=True, format=True)) == ["format", "speak"]
    assert _selected_stages(_ns(clean=True)) == ["clean"]
    assert _selected_stages(_ns(extract=True, speak=True, clean=True, format=True)) == [
        "extract",
        "clean",
        "format",
        "speak",
    ]


def test_x_vector_only_cli_flags(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run(config, **kwargs):
        captured.clear()
        captured.update(kwargs)
        return 0

    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("text2audiobook.pipeline.run", fake_run)
    monkeypatch.setattr("text2audiobook.gpu.prepare_gpu_env", lambda: None)

    assert main(["--config", str(config_path), "--speak", "--x-vector-only"]) == 0
    assert captured.get("x_vector_only") is True

    assert main(["--config", str(config_path), "--speak", "--icl"]) == 0
    assert captured.get("x_vector_only") is False

    assert main(["--config", str(config_path), "--speak"]) == 0
    assert captured.get("x_vector_only") is None

    # Sanity: empty config still loads.
    assert load_config(config_path).tts.x_vector_only is True
