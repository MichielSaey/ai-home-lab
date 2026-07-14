"""Pre-built running workout templates with MCP-managed heart rate zones."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from nutrition_matrix import inject_nutrition_cues, intensity_for_template
from workout_builder import build_running_workout, estimate_steps_duration_seconds

TEMPLATE_TYPES = (
    "base",
    "long_run",
    "recovery",
    "threshold",
    "sprint",
    "hill_repeats",
    "weighted_pack",
)

# Aliases are named variants that reuse another template's build. They differ
# only in intent/label, not in structure or zone:
# - hill_repeats: sprints run on a hill (no separate elevation metric)
# - weighted_pack: a base run carrying a loaded pack (rucking)
TEMPLATE_ALIASES: Dict[str, str] = {
    "hill_repeats": "sprint",
    "weighted_pack": "base",
}


def _base_steps(duration_minutes: int) -> List[Dict[str, Any]]:
    return [
        {
            "type": "interval",
            "duration_minutes": duration_minutes,
            "workout_type": "base",
        }
    ]


def build_base_workout_steps(duration_minutes: int) -> List[Dict[str, Any]]:
    return _base_steps(duration_minutes)


def build_long_run_workout_steps(duration_minutes: int) -> List[Dict[str, Any]]:
    return [
        {
            "type": "interval",
            "duration_minutes": duration_minutes,
            "workout_type": "long_run",
        }
    ]


def build_recovery_workout_steps(duration_minutes: int) -> List[Dict[str, Any]]:
    return [
        {
            "type": "interval",
            "duration_minutes": duration_minutes,
            "workout_type": "recovery",
        }
    ]


def build_threshold_workout_steps(
    repetitions: int = 4,
    interval_minutes: int = 5,
    recovery_minutes: int = 2,
    warmup_minutes: int = 10,
    cooldown_minutes: int = 10,
) -> List[Dict[str, Any]]:
    return [
        {"type": "warmup", "duration_minutes": warmup_minutes, "workout_type": "warmup"},
        {
            "type": "repeat",
            "iterations": repetitions,
            "steps": [
                {
                    "type": "interval",
                    "duration_minutes": interval_minutes,
                    "workout_type": "threshold",
                },
                {
                    "type": "recovery",
                    "duration_minutes": recovery_minutes,
                    "workout_type": "interval_recovery",
                },
            ],
        },
        {
            "type": "cooldown",
            "duration_minutes": cooldown_minutes,
            "workout_type": "cooldown",
        },
    ]


def build_sprint_workout_steps(
    repetitions: int = 6,
    sprint_seconds: int = 30,
    recovery_seconds: int = 90,
    warmup_minutes: int = 15,
    cooldown_minutes: int = 10,
) -> List[Dict[str, Any]]:
    return [
        {"type": "warmup", "duration_minutes": warmup_minutes, "workout_type": "warmup"},
        {
            "type": "repeat",
            "iterations": repetitions,
            "steps": [
                {
                    "type": "interval",
                    "duration_minutes": sprint_seconds / 60.0,
                    "workout_type": "sprint",
                },
                {
                    "type": "recovery",
                    "duration_minutes": recovery_seconds / 60.0,
                    "workout_type": "interval_recovery",
                },
            ],
        },
        {
            "type": "cooldown",
            "duration_minutes": cooldown_minutes,
            "workout_type": "cooldown",
        },
    ]


def build_template_steps(template: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    params = params or {}
    template_key = TEMPLATE_ALIASES.get(template.lower(), template.lower())

    if template_key == "base":
        return build_base_workout_steps(int(params.get("duration_minutes", 30)))
    if template_key == "long_run":
        return build_long_run_workout_steps(int(params.get("duration_minutes", 90)))
    if template_key == "recovery":
        return build_recovery_workout_steps(int(params.get("duration_minutes", 25)))
    if template_key == "threshold":
        if "duration_minutes" in params:
            raise ValueError(
                "threshold template no longer accepts duration_minutes; "
                "use repetitions and interval_minutes instead."
            )
        return build_threshold_workout_steps(
            repetitions=int(params.get("repetitions", 4)),
            interval_minutes=int(params.get("interval_minutes", 5)),
            recovery_minutes=int(params.get("recovery_minutes", 2)),
            warmup_minutes=int(params.get("warmup_minutes", 10)),
            cooldown_minutes=int(params.get("cooldown_minutes", 10)),
        )
    if template_key == "sprint":
        return build_sprint_workout_steps(
            repetitions=int(params.get("repetitions", 6)),
            sprint_seconds=int(params.get("sprint_seconds", 30)),
            recovery_seconds=int(params.get("recovery_seconds", 90)),
            warmup_minutes=int(params.get("warmup_minutes", 15)),
            cooldown_minutes=int(params.get("cooldown_minutes", 10)),
        )

    raise ValueError(
        f"Unknown template '{template}'. Supported templates: {', '.join(TEMPLATE_TYPES)}."
    )




def estimate_template_duration_minutes(
    template: str,
    params: Optional[Dict[str, Any]] = None,
) -> int:
    steps = build_template_steps(template, params)
    return max(estimate_steps_duration_seconds(steps) // 60, 1)


def estimate_combined_duration_minutes(segments: List[Dict[str, Any]]) -> int:
    total_seconds = 0
    for segment in segments:
        if "steps" in segment and isinstance(segment["steps"], list):
            total_seconds += estimate_steps_duration_seconds(segment["steps"])
            continue
        template = segment.get("template")
        if not template:
            continue
        total_seconds += estimate_steps_duration_seconds(
            build_template_steps(str(template), segment.get("params", {}))
        )
    return max(total_seconds // 60, 1)

def combine_template_steps(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not segments:
        raise ValueError("Provide at least one template segment to combine.")

    combined: List[Dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Each segment must be an object.")
        if "steps" in segment and isinstance(segment["steps"], list):
            combined.extend(segment["steps"])
            continue
        template = segment.get("template")
        if not template:
            raise ValueError("Each segment needs 'template' or explicit 'steps'.")
        combined.extend(build_template_steps(str(template), segment.get("params", {})))
    return combined


def build_template_workout(
    name: str,
    template: str,
    params: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    include_nutrition_cues: bool = False,
):
    steps = build_template_steps(template, params)
    if include_nutrition_cues:
        duration_minutes = estimate_template_duration_minutes(template, params)
        steps = inject_nutrition_cues(
            steps,
            duration_minutes,
            intensity=intensity_for_template(template),
        )
    return build_running_workout(name, steps, description=description)


def build_combined_workout(
    name: str,
    segments: List[Dict[str, Any]],
    description: Optional[str] = None,
    include_nutrition_cues: bool = False,
):
    steps = combine_template_steps(segments)
    if include_nutrition_cues:
        duration_minutes = estimate_combined_duration_minutes(segments)
        primary_template = str(segments[0].get("template", "base")) if segments else "base"
        steps = inject_nutrition_cues(
            steps,
            duration_minutes,
            intensity=intensity_for_template(primary_template),
        )
    return build_running_workout(name, steps, description=description)


TEMPLATE_DESCRIPTIONS = {
    "base": "Single continuous easy aerobic run in HR zone 2.",
    "long_run": "Extended easy aerobic run in HR zone 2.",
    "recovery": "Short recovery jog in HR zone 1.",
    "threshold": "Warmup, lactate-threshold repeats in HR zone 4 with recoveries, cooldown.",
    "sprint": "Warmup, short max-effort sprints in HR zone 5 with jog recoveries, cooldown.",
    "hill_repeats": "Sprints run uphill: warmup, max-effort hill reps in HR zone 5 with jog recoveries, cooldown.",
    "weighted_pack": "Base aerobic run in HR zone 2 carrying a loaded pack (rucking).",
}
