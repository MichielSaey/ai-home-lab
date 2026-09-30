"""Garmin Connect self-evaluation: written notes, plus feel/RPE scores."""

from __future__ import annotations

from typing import Any

# Garmin stores How Did You Feel? as 0/25/50/75/100.
_FEELING_SCORES = (0, 25, 50, 75, 100)
_FEELING_LABELS = {
    0: "Very Weak",
    25: "Weak",
    50: "Normal",
    75: "Strong",
    100: "Very Strong",
}

# Free-text fields the athlete can fill in on an activity. ``description`` is
# the Connect "Description" / notes box — that is self-evaluation. ``comments``
# is a less common string field on the list payload.
_NOTE_KEYS = ("description", "comments")


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _note_from_payload(payload: dict[str, Any] | None) -> str | None:
    """Return the athlete's written note, not numeric feel/RPE."""
    if not isinstance(payload, dict):
        return None
    parts: list[str] = []
    for key in _NOTE_KEYS:
        text = _clean_text(payload.get(key))
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return None
    return "\n".join(parts)


def feeling_label(score: Any) -> str | None:
    """Map Garmin ``directWorkoutFeel`` (0–100) to the Connect UI labels."""
    if score is None:
        return None
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return None
    nearest = min(_FEELING_SCORES, key=lambda candidate: abs(candidate - numeric))
    return _FEELING_LABELS[nearest]


def perceived_effort(raw: Any) -> float | None:
    """Normalize Garmin ``directWorkoutRpe`` to a 1–10 scale.

    Connect stores RPE as 10–100 (RPE × 10). Values already below 10 are
    left as-is. Zero / missing is treated as unset.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # 10 is RPE 1 on Connect (10–100 encoding), not a pre-scaled 10.
    if value >= 10:
        value = value / 10.0
    return round(value, 1)


def _scores_from_payload(payload: dict[str, Any] | None) -> tuple[str | None, float | None]:
    if not isinstance(payload, dict):
        return None, None
    summary = payload.get("summaryDTO")
    feeling = None
    effort = None
    if isinstance(summary, dict):
        feeling = feeling_label(summary.get("directWorkoutFeel"))
        effort = perceived_effort(summary.get("directWorkoutRpe"))
    feeling = feeling or feeling_label(payload.get("directWorkoutFeel"))
    effort = effort or perceived_effort(payload.get("directWorkoutRpe"))
    return feeling, effort


def extract_self_evaluation(
    list_activity: dict[str, Any] | None = None,
    detail: Any = None,
) -> dict[str, Any]:
    """Pull the written self-evaluation note plus optional feel/RPE scores.

    ``self_evaluation`` is free text (Garmin activity Description / notes).
    ``feeling`` and ``perceived_effort`` are extra numeric ratings from
    ``summaryDTO`` and are not a substitute for the note.
    """
    note: str | None = None
    feeling: str | None = None
    effort: float | None = None

    list_note = _note_from_payload(list_activity)
    list_feeling, list_effort = _scores_from_payload(list_activity)
    note = list_note
    feeling = list_feeling
    effort = list_effort

    if isinstance(detail, dict) and not detail.get("error"):
        note = _note_from_payload(detail) or note
        detail_feeling, detail_effort = _scores_from_payload(detail)
        feeling = detail_feeling or feeling
        effort = detail_effort if detail_effort is not None else effort

    return {
        "self_evaluation": note,
        "feeling": feeling,
        "perceived_effort": effort,
    }
