"""Premade nutrition guidance keyed by expected workout duration."""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class PhaseCues(TypedDict):
    eat: str
    drink: str


class NutritionBucket(TypedDict):
    key: str
    label: str
    min_minutes: int
    max_minutes: int | None
    before: PhaseCues
    during: PhaseCues
    after: PhaseCues


NUTRITION_MATRIX: tuple[NutritionBucket, ...] = (
    {
        "key": "short",
        "label": "Short run (under 45 min)",
        "min_minutes": 1,
        "max_minutes": 44,
        "before": {
            "eat": "Optional light snack if hungry; no heavy meal within 60 min.",
            "drink": "250-500 ml water 1-2 hours before.",
        },
        "during": {
            "eat": "No fuel needed for most runners.",
            "drink": "Small sips if hot; otherwise drink to thirst.",
        },
        "after": {
            "eat": "Normal balanced meal within 1-2 hours.",
            "drink": "Rehydrate with ~500 ml water.",
        },
    },
    {
        "key": "medium",
        "label": "Medium run (45-74 min)",
        "min_minutes": 45,
        "max_minutes": 74,
        "before": {
            "eat": "Carb-rich snack 60-90 min before (banana, toast, or bar).",
            "drink": "400-500 ml water in the 2 hours before.",
        },
        "during": {
            "eat": "Optional gel or chews if effort is hard or run exceeds 60 min.",
            "drink": "150-250 ml every 20 min in heat.",
        },
        "after": {
            "eat": "Carbs + protein within 30-60 min (yogurt, sandwich, or shake).",
            "drink": "500-750 ml over the next hour.",
        },
    },
    {
        "key": "long",
        "label": "Long run (75-119 min)",
        "min_minutes": 75,
        "max_minutes": 119,
        "before": {
            "eat": "Carb-focused meal 2-3 hours before; light top-up 30-60 min pre-run.",
            "drink": "500 ml water plus electrolytes if warm.",
        },
        "during": {
            "eat": "30-60 g carbs/hour via gel, chews, or dates every 30-45 min.",
            "drink": "150-250 ml every 15-20 min.",
        },
        "after": {
            "eat": "Recovery meal with carbs and 20-30 g protein within 60 min.",
            "drink": "750 ml+ over 1-2 hours.",
        },
    },
    {
        "key": "ultra",
        "label": "Ultra / very long run (120+ min)",
        "min_minutes": 120,
        "max_minutes": None,
        "before": {
            "eat": "High-carb meal 3 hours before; small carb snack 30-45 min pre-run.",
            "drink": "750 ml+ water/electrolytes in the 2 hours before.",
        },
        "during": {
            "eat": "30-90 g carbs/hour on a steady schedule; practice race-day foods.",
            "drink": "200-250 ml every 15 min; add electrolytes after 60 min.",
        },
        "after": {
            "eat": "Recovery meal plus snack over 2 hours; prioritize carbs and protein.",
            "drink": "1 L+ over 2-3 hours based on sweat loss.",
        },
    },
)


INTENSITY_ALIASES: dict[str, str] = {
    "easy": "easy",
    "recovery": "easy",
    "long_run": "easy",
    "long": "easy",
    "moderate": "moderate",
    "tempo": "moderate",
    "hard": "hard",
    "threshold": "hard",
    "strides": "hard",
    "sprint": "hard",
}

INTENSITY_ADJUSTMENTS: dict[str, dict[str, str]] = {
    "easy": {},
    "moderate": {
        "during_eat_suffix": " Prioritize carbs if pace feels demanding.",
        "during_drink_suffix": " Sip regularly rather than waiting for thirst.",
    },
    "hard": {
        "before_eat_suffix": " Favor easily digestible carbs 60-90 min before.",
        "during_eat_suffix": " Take 15-30 g carbs every 30-40 min even on shorter hard efforts.",
        "during_drink_suffix": " Drink 150-200 ml every 15-20 min; add electrolytes when sweaty.",
    },
}

TEMPLATE_INTENSITY: dict[str, str] = {
    "easy": "easy",
    "long_run": "easy",
    "recovery": "easy",
    "tempo": "moderate",
    "threshold": "hard",
    "strides": "hard",
    "sprint": "hard",
}


def normalize_intensity(intensity: str = "easy") -> str:
    key = intensity.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = INTENSITY_ALIASES.get(key)
    if normalized is None:
        raise ValueError(
            f"Unsupported intensity '{intensity}'. Use easy, moderate, or hard."
        )
    return normalized


def intensity_for_template(template: str) -> str:
    return TEMPLATE_INTENSITY.get(template.strip().lower(), "easy")


def _apply_intensity(cues: PhaseCues, intensity: str, phase: str) -> PhaseCues:
    adjustments = INTENSITY_ADJUSTMENTS.get(intensity, {})
    eat_key = f"{phase}_eat_suffix"
    drink_key = f"{phase}_drink_suffix"
    return {
        "eat": cues["eat"] + adjustments.get(eat_key, ""),
        "drink": cues["drink"] + adjustments.get(drink_key, ""),
    }



def resolve_duration_bucket(duration_minutes: int) -> NutritionBucket:
    if duration_minutes < 1:
        raise ValueError("duration_minutes must be at least 1")

    for bucket in NUTRITION_MATRIX:
        max_minutes = bucket["max_minutes"]
        if duration_minutes >= bucket["min_minutes"] and (
            max_minutes is None or duration_minutes <= max_minutes
        ):
            return bucket

    return NUTRITION_MATRIX[-1]


def get_nutrition_cues(
    duration_minutes: int,
    intensity: str = "easy",
) -> Dict[str, Any]:
    """Return structured before/during/after eat and drink cues for a workout duration."""
    normalized_intensity = normalize_intensity(intensity)
    bucket = resolve_duration_bucket(duration_minutes)
    return {
        "duration_minutes": duration_minutes,
        "intensity": normalized_intensity,
        "bucket": bucket["key"],
        "label": bucket["label"],
        "before": _apply_intensity(bucket["before"], normalized_intensity, "before"),
        "during": _apply_intensity(bucket["during"], normalized_intensity, "during"),
        "after": _apply_intensity(bucket["after"], normalized_intensity, "after"),
    }


def nutrition_cue_steps(
    duration_minutes: int,
    intensity: str = "easy",
) -> List[Dict[str, Any]]:
    """Build Garmin cue steps that surface nutrition reminders on the watch."""
    cues = get_nutrition_cues(duration_minutes, intensity=intensity)
    return [
        {
            "type": "cue",
            "message": (
                f"BEFORE — Eat: {cues['before']['eat']} "
                f"| Drink: {cues['before']['drink']}"
            ),
        },
        {
            "type": "cue",
            "message": (
                f"DURING — Eat: {cues['during']['eat']} "
                f"| Drink: {cues['during']['drink']}"
            ),
        },
        {
            "type": "cue",
            "message": (
                f"AFTER — Eat: {cues['after']['eat']} "
                f"| Drink: {cues['after']['drink']}"
            ),
        },
    ]


def inject_nutrition_cues(
    steps: List[Dict[str, Any]],
    duration_minutes: int,
    intensity: str = "easy",
) -> List[Dict[str, Any]]:
    """Insert before, midpoint during, and after nutrition cue steps."""
    if not steps:
        raise ValueError("At least one workout step is required.")

    before, during, after = nutrition_cue_steps(duration_minutes, intensity=intensity)
    midpoint = max(1, len(steps) // 2)
    return [before, *steps[:midpoint], during, *steps[midpoint:], after]
