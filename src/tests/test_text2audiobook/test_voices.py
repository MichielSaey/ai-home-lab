from pathlib import Path

from text2audiobook.voices import (
    RANDOM_POOL,
    lang_for_voice,
    list_voices,
    pick_random_voice,
    resolve_voice,
)


def test_lang_follows_speaker_native() -> None:
    assert lang_for_voice("Ryan") == "English"
    assert lang_for_voice("Aiden") == "English"
    assert lang_for_voice("Vivian") == "Chinese"
    assert lang_for_voice("Ono_Anna") == "Japanese"


def test_random_pool_is_all_custom_voices() -> None:
    names = {voice.name for voice in list_voices()}
    assert set(RANDOM_POOL) == names
    assert "Ryan" in RANDOM_POOL
    assert "Aiden" in RANDOM_POOL
    assert "Vivian" in RANDOM_POOL


def test_random_without_replacement_then_wraps(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    seen: list[str] = []
    for _ in range(len(RANDOM_POOL)):
        seen.append(pick_random_voice(state))
    assert sorted(seen) == sorted(RANDOM_POOL)
    seen.append(pick_random_voice(state))
    assert seen[-1] in RANDOM_POOL


def test_resolve_voice_default_and_named(tmp_path: Path) -> None:
    assert resolve_voice(None, default="Ryan", state_path=tmp_path / "s.json") == "Ryan"
    assert resolve_voice("Aiden", default="Ryan", state_path=tmp_path / "s.json") == "Aiden"
    assert resolve_voice(None, default="designed", state_path=tmp_path / "s.json") == "designed"
    assert resolve_voice("VoiceDesign", default="designed", state_path=tmp_path / "s.json") == "designed"
    assert resolve_voice(None, default="", state_path=tmp_path / "s.json") == "designed"


def test_resolve_voice_rejects_unknown_default(tmp_path: Path) -> None:
    try:
        resolve_voice(None, default="af_bella", state_path=tmp_path / "s.json")
    except ValueError as exc:
        assert "af_bella" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown default voice")


def test_format_voice_table_mentions_voicedesign() -> None:
    from text2audiobook.voices import format_voice_table

    table = format_voice_table()
    assert "Serena" in table
    assert "VoiceDesign" in table
    assert "designed" in table
