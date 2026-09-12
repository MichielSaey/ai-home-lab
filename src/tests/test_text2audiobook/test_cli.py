"""CLI stage-flag selection."""

import argparse

from text2audiobook.cli import _selected_stages


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
