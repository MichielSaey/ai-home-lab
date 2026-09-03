from pathlib import Path

from text2audiobook.voices import (
    RANDOM_POOL,
    lang_for_voice,
    list_voices,
    pick_random_voice,
    resolve_voice,
)


def test_lang_follows_voice_prefix() -> None:
    assert lang_for_voice("af_bella") == "a"
    assert lang_for_voice("bf_emma") == "b"
    assert lang_for_voice("ff_siwis") == "f"


def test_random_pool_is_top_grades_only() -> None:
    names = {voice.name for voice in list_voices() if voice.grade in {"A", "A-", "B-"}}
    assert set(RANDOM_POOL) == names
    assert "af_bella" in RANDOM_POOL
    assert "bf_emma" in RANDOM_POOL
    assert "af_heart" in RANDOM_POOL


def test_random_without_replacement_then_wraps(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    seen: list[str] = []
    for _ in range(len(RANDOM_POOL)):
        seen.append(pick_random_voice(state))
    assert sorted(seen) == sorted(RANDOM_POOL)
    seen.append(pick_random_voice(state))
    assert seen[-1] in RANDOM_POOL


def test_resolve_voice_default_and_named(tmp_path: Path) -> None:
    assert resolve_voice(None, default="af_bella", state_path=tmp_path / "s.json") == "af_bella"
    assert resolve_voice("bf_emma", default="af_bella", state_path=tmp_path / "s.json") == "bf_emma"
