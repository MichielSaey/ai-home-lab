"""Kokoro voice catalog, CLI listing, and random-without-replacement picks."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

RANDOM_GRADES = frozenset({"A", "A-", "B-"})


@dataclass(frozen=True)
class VoiceInfo:
    name: str
    grade: str
    language: str
    lang_code: str


# Official Kokoro-82M grades (VOICES.md). Ungraded locale voices are listed as "?".
VOICES: tuple[VoiceInfo, ...] = (
    VoiceInfo("af_heart", "A", "American English", "a"),
    VoiceInfo("af_bella", "A-", "American English", "a"),
    VoiceInfo("af_nicole", "B-", "American English", "a"),
    VoiceInfo("af_aoede", "C+", "American English", "a"),
    VoiceInfo("af_kore", "C+", "American English", "a"),
    VoiceInfo("af_sarah", "C+", "American English", "a"),
    VoiceInfo("am_fenrir", "C+", "American English", "a"),
    VoiceInfo("am_michael", "C+", "American English", "a"),
    VoiceInfo("am_puck", "C+", "American English", "a"),
    VoiceInfo("af_alloy", "C", "American English", "a"),
    VoiceInfo("af_nova", "C", "American English", "a"),
    VoiceInfo("af_sky", "C-", "American English", "a"),
    VoiceInfo("af_jessica", "D", "American English", "a"),
    VoiceInfo("af_river", "D", "American English", "a"),
    VoiceInfo("am_echo", "D", "American English", "a"),
    VoiceInfo("am_eric", "D", "American English", "a"),
    VoiceInfo("am_liam", "D", "American English", "a"),
    VoiceInfo("am_onyx", "D", "American English", "a"),
    VoiceInfo("am_santa", "D-", "American English", "a"),
    VoiceInfo("am_adam", "F+", "American English", "a"),
    VoiceInfo("bf_emma", "B-", "British English", "b"),
    VoiceInfo("bf_isabella", "C", "British English", "b"),
    VoiceInfo("bm_fable", "C", "British English", "b"),
    VoiceInfo("bm_george", "C", "British English", "b"),
    VoiceInfo("bf_alice", "D", "British English", "b"),
    VoiceInfo("bf_lily", "D", "British English", "b"),
    VoiceInfo("bm_daniel", "D", "British English", "b"),
    VoiceInfo("bm_lewis", "D+", "British English", "b"),
    VoiceInfo("ff_siwis", "B-", "French", "f"),
    VoiceInfo("jf_alpha", "C+", "Japanese", "j"),
    VoiceInfo("jf_gongitsune", "C", "Japanese", "j"),
    VoiceInfo("jf_tebukuro", "C", "Japanese", "j"),
    VoiceInfo("jf_nezumi", "C-", "Japanese", "j"),
    VoiceInfo("jm_kumo", "C-", "Japanese", "j"),
    VoiceInfo("zf_xiaobei", "D", "Mandarin Chinese", "z"),
    VoiceInfo("zf_xiaoni", "D", "Mandarin Chinese", "z"),
    VoiceInfo("zf_xiaoxiao", "D", "Mandarin Chinese", "z"),
    VoiceInfo("zf_xiaoyi", "D", "Mandarin Chinese", "z"),
    VoiceInfo("zm_yunjian", "D", "Mandarin Chinese", "z"),
    VoiceInfo("zm_yunxi", "D", "Mandarin Chinese", "z"),
    VoiceInfo("zm_yunxia", "D", "Mandarin Chinese", "z"),
    VoiceInfo("zm_yunyang", "D", "Mandarin Chinese", "z"),
    VoiceInfo("hf_alpha", "C", "Hindi", "h"),
    VoiceInfo("hf_beta", "C", "Hindi", "h"),
    VoiceInfo("hm_omega", "C", "Hindi", "h"),
    VoiceInfo("hm_psi", "C", "Hindi", "h"),
    VoiceInfo("if_sara", "C", "Italian", "i"),
    VoiceInfo("im_nicola", "C", "Italian", "i"),
    VoiceInfo("ef_dora", "?", "Spanish", "e"),
    VoiceInfo("em_alex", "?", "Spanish", "e"),
    VoiceInfo("em_santa", "?", "Spanish", "e"),
    VoiceInfo("pf_dora", "?", "Brazilian Portuguese", "p"),
    VoiceInfo("pm_alex", "?", "Brazilian Portuguese", "p"),
    VoiceInfo("pm_santa", "?", "Brazilian Portuguese", "p"),
)

_BY_NAME = {voice.name: voice for voice in VOICES}
RANDOM_POOL: tuple[str, ...] = tuple(
    voice.name for voice in VOICES if voice.grade in RANDOM_GRADES
)


def lang_for_voice(name: str) -> str:
    known = _BY_NAME.get(name)
    if known is not None:
        return known.lang_code
    if name:
        return name[0].lower()
    return "a"


def get_voice(name: str) -> VoiceInfo | None:
    return _BY_NAME.get(name)


def list_voices() -> list[VoiceInfo]:
    """Return the baked Kokoro-82M catalog (same ids as voices/*.pt on the Hub)."""
    return list(VOICES)


def format_voice_table(voices: list[VoiceInfo] | None = None) -> str:
    rows = voices if voices is not None else list_voices()
    lines = [f"{'name':<16} {'grade':<4} language"]
    for voice in rows:
        lines.append(f"{voice.name:<16} {voice.grade:<4} {voice.language}")
    return "\n".join(lines)


def random_pool() -> tuple[str, ...]:
    return RANDOM_POOL


def pick_random_voice(
    state_path: Path,
    *,
    rng: random.Random | None = None,
) -> str:
    """Pick the next A / A- / B- voice without replacement until the pool wraps."""
    pool = list(RANDOM_POOL)
    rng = rng or random.Random()
    remaining = _load_remaining(state_path, pool)
    if not remaining:
        remaining = pool
        rng.shuffle(remaining)
    voice = remaining.pop(0)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"remaining": remaining}, indent=2) + "\n", encoding="utf-8"
    )
    return voice


def resolve_voice(
    requested: str | None,
    *,
    default: str,
    state_path: Path,
    rng: random.Random | None = None,
) -> str:
    if requested is None or requested.strip() == "":
        return default
    name = requested.strip()
    if name.lower() == "random":
        return pick_random_voice(state_path, rng=rng)
    if name not in _BY_NAME and not _looks_like_voice(name):
        known = ", ".join(voice.name for voice in VOICES)
        raise ValueError(f"Unknown voice {name!r}. Known voices: {known}")
    return name


def _looks_like_voice(name: str) -> bool:
    return bool(name) and "_" in name and name[0].isalpha()


def _load_remaining(state_path: Path, pool: list[str]) -> list[str]:
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        remaining = [item for item in data.get("remaining", []) if item in pool]
        return remaining
    except (json.JSONDecodeError, TypeError, AttributeError):
        logger.debug("Ignoring invalid voice-random state at %s", state_path)
        return []
