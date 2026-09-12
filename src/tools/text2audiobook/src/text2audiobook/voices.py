"""Qwen3-TTS CustomVoice catalog, VoiceDesign / Base clone labels, CLI listing."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Labels for VoiceDesign (no fixed speaker; timbre from instruct).
VOICE_DESIGN_LABEL = "designed"
VOICE_DESIGN_ALIASES = frozenset({"designed", "voicedesign"})

# Labels for Base voice cloning (timbre from ref_audio + ref_text).
VOICE_CLONE_LABEL = "cloned"
VOICE_CLONE_ALIASES = frozenset({"cloned", "clone", "base"})


@dataclass(frozen=True)
class VoiceInfo:
    name: str
    description: str
    language: str


# Official Qwen3-TTS CustomVoice speakers (model card).
VOICES: tuple[VoiceInfo, ...] = (
    VoiceInfo("Vivian", "Bright, slightly edgy young female voice", "Chinese"),
    VoiceInfo("Serena", "Warm, gentle young female voice", "Chinese"),
    VoiceInfo("Uncle_Fu", "Seasoned male voice with a low, mellow timbre", "Chinese"),
    VoiceInfo("Dylan", "Youthful Beijing male voice with a clear, natural timbre", "Chinese"),
    VoiceInfo("Eric", "Lively Chengdu male voice with a slightly husky brightness", "Chinese"),
    VoiceInfo("Ryan", "Dynamic male voice with strong rhythmic drive", "English"),
    VoiceInfo("Aiden", "Sunny American male voice with a clear midrange", "English"),
    VoiceInfo("Ono_Anna", "Playful Japanese female voice with a light, nimble timbre", "Japanese"),
    VoiceInfo("Sohee", "Warm Korean female voice with rich emotion", "Korean"),
)

_BY_NAME = {voice.name: voice for voice in VOICES}
_BY_NAME_CI = {voice.name.lower(): voice for voice in VOICES}
RANDOM_POOL: tuple[str, ...] = tuple(voice.name for voice in VOICES)


def is_voice_design_label(name: str | None) -> bool:
    if name is None:
        return False
    return name.strip().lower() in VOICE_DESIGN_ALIASES


def is_voice_clone_label(name: str | None) -> bool:
    if name is None:
        return False
    return name.strip().lower() in VOICE_CLONE_ALIASES


def lang_for_voice(name: str) -> str:
    """Return the speaker's recommended Qwen language string."""
    if is_voice_design_label(name) or is_voice_clone_label(name):
        return "English"
    known = _BY_NAME.get(name) or _BY_NAME_CI.get(name.lower())
    if known is not None:
        return known.language
    return "English"


def get_voice(name: str) -> VoiceInfo | None:
    return _BY_NAME.get(name) or _BY_NAME_CI.get(name.lower())


def list_voices() -> list[VoiceInfo]:
    """Return the baked Qwen3-TTS CustomVoice catalog."""
    return list(VOICES)


def format_voice_table(voices: list[VoiceInfo] | None = None) -> str:
    rows = voices if voices is not None else list_voices()
    lines = [f"{'name':<12} {'language':<10} description"]
    for voice in rows:
        lines.append(f"{voice.name:<12} {voice.language:<10} {voice.description}")
    lines.append("")
    lines.append(
        "CustomVoice speakers are listed above. Base models clone from "
        "tts.ref_audio (+ tts.ref_text); use voice label 'cloned'. "
        "VoiceDesign models have no fixed speakers — timbre comes from "
        "tts.instruct; use voice label 'designed'."
    )
    return "\n".join(lines)


def random_pool() -> tuple[str, ...]:
    return RANDOM_POOL


def pick_random_voice(
    state_path: Path,
    *,
    rng: random.Random | None = None,
) -> str:
    """Pick the next CustomVoice speaker without replacement until the pool wraps."""
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
    allow_design_label: bool = True,
) -> str:
    """Resolve a voice name for VoiceDesign or CustomVoice.

    When ``allow_design_label`` is False (CustomVoice), ``designed`` /
    ``VoiceDesign`` are rejected so they never reach ``generate_custom_voice``.
    Base clone labels are handled in the pipeline (``is_base``), not here.
    """
    if requested is None or requested.strip() == "":
        if not default or not str(default).strip() or is_voice_design_label(default):
            if not allow_design_label:
                known_names = ", ".join(voice.name for voice in VOICES)
                raise ValueError(
                    f"CustomVoice requires a catalog speaker, not {default!r}. "
                    f"Known voices: {known_names}"
                )
            return VOICE_DESIGN_LABEL
        known = get_voice(default)
        if known is None:
            known_names = ", ".join(voice.name for voice in VOICES)
            raise ValueError(
                f"Unknown default voice {default!r}. Known voices: {known_names} "
                f"(or '{VOICE_DESIGN_LABEL}' for VoiceDesign)"
            )
        return known.name
    name = requested.strip()
    if is_voice_design_label(name):
        if not allow_design_label:
            known_names = ", ".join(voice.name for voice in VOICES)
            raise ValueError(
                f"Voice {name!r} is for VoiceDesign only. "
                f"Use a CustomVoice speaker: {known_names}"
            )
        return VOICE_DESIGN_LABEL
    if name.lower() == "random":
        return pick_random_voice(state_path, rng=rng)
    known = get_voice(name)
    if known is not None:
        return known.name
    known_names = ", ".join(voice.name for voice in VOICES)
    raise ValueError(
        f"Unknown voice {name!r}. Known voices: {known_names} "
        f"(or '{VOICE_DESIGN_LABEL}' for VoiceDesign)"
    )


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
