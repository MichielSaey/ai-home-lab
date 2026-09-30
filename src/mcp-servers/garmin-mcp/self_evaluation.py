"""Garmin Connect self-evaluation: activity comments, feel, and RPE."""

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


def _clean_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


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

    Connect stores RPE as 10–100 (divide by 10). Values already on 1–10 are
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
    if value > 10:
        value = value / 10.0
    return round(value, 1)


def extract_self_evaluation(
    list_activity: dict[str, Any] | None = None,
    detail: Any = None,
) -> dict[str, Any]:
    """Pull comment + self-evaluation from a list row and/or ``get_activity``.

    ``get_activities_by_date`` may include ``description`` (the message the
    athlete added). Feel and perceived effort live on the activity-detail
    ``summaryDTO`` (``directWorkoutFeel``, ``directWorkoutRpe``).
    """
    message: str | None = None
    feeling: str | None = None
    effort: float | None = None

    if isinstance(list_activity, dict):
        message = _clean_message(list_activity.get("description"))
        summary = list_activity.get("summaryDTO")
        if isinstance(summary, dict):
            feeling = feeling_label(summary.get("directWorkoutFeel"))
            effort = perceived_effort(summary.get("directWorkoutRpe"))
        feeling = feeling or feeling_label(list_activity.get("directWorkoutFeel"))
        effort = effort or perceived_effort(list_activity.get("directWorkoutRpe"))

    if isinstance(detail, dict) and not detail.get("error"):
        message = _clean_message(detail.get("description")) or message
        summary = detail.get("summaryDTO")
        if isinstance(summary, dict):
            feeling = feeling_label(summary.get("directWorkoutFeel")) or feeling
            effort = perceived_effort(summary.get("directWorkoutRpe")) or effort

    return {
        "message": message,
        "feeling": feeling,
        "perceived_effort": effort,
    }


def has_self_evaluation_content(evaluation: dict[str, Any] | None) -> bool:
    if not isinstance(evaluation, dict):
        return False
    return bool(
        evaluation.get("message")
        or evaluation.get("feeling")
        or evaluation.get("perceived_effort") is not None
    )
