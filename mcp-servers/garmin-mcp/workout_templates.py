"""Pre-built running workout templates with MCP-managed heart rate zones."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from workout_builder import build_running_workout

TEMPLATE_TYPES = (
    "easy",
    "long_run",
    "recovery",
    "tempo",
    "threshold",
    "strides",
    "sprint",
)


def _easy_steps(duration_minutes: int) -> List[Dict[str, Any]]:
    return [
        {
            "type": "interval",
            "duration_minutes": duration_minutes,
            "workout_type": "easy",
        }
    ]


def build_easy_workout_steps(duration_minutes: int) -> List[Dict[str, Any]]:
    return _easy_steps(duration_minutes)


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


def build_tempo_workout_steps(
    tempo_minutes: int,
    warmup_minutes: int = 10,
    cooldown_minutes: int = 10,
) -> List[Dict[str, Any]]:
    return [
        {"type": "warmup", "duration_minutes": warmup_minutes, "workout_type": "warmup"},
        {
            "type": "interval",
            "duration_minutes": tempo_minutes,
            "workout_type": "tempo",
        },
        {
            "type": "cooldown",
            "duration_minutes": cooldown_minutes,
            "workout_type": "cooldown",
        },
    ]


def build_threshold_workout_steps(
    threshold_minutes: int,
    warmup_minutes: int = 10,
    cooldown_minutes: int = 10,
) -> List[Dict[str, Any]]:
    return [
        {"type": "warmup", "duration_minutes": warmup_minutes, "workout_type": "warmup"},
        {
            "type": "interval",
            "duration_minutes": threshold_minutes,
            "workout_type": "threshold",
        },
        {
            "type": "cooldown",
            "duration_minutes": cooldown_minutes,
            "workout_type": "cooldown",
        },
    ]


def build_strides_workout_steps(
    count: int = 6,
    stride_seconds: int = 20,
    recovery_seconds: int = 60,
    warmup_minutes: int = 15,
    cooldown_minutes: int = 10,
) -> List[Dict[str, Any]]:
    return [
        {"type": "warmup", "duration_minutes": warmup_minutes, "workout_type": "warmup"},
        {
            "type": "repeat",
            "iterations": count,
            "steps": [
                {
                    "type": "interval",
                    "duration_minutes": stride_seconds / 60.0,
                    "workout_type": "strides",
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
    template_key = template.lower()

    if template_key == "easy":
        return build_easy_workout_steps(int(params.get("duration_minutes", 30)))
    if template_key == "long_run":
        return build_long_run_workout_steps(int(params.get("duration_minutes", 90)))
    if template_key == "recovery":
        return build_recovery_workout_steps(int(params.get("duration_minutes", 25)))
    if template_key == "tempo":
        return build_tempo_workout_steps(
            tempo_minutes=int(params.get("duration_minutes", 20)),
            warmup_minutes=int(params.get("warmup_minutes", 10)),
            cooldown_minutes=int(params.get("cooldown_minutes", 10)),
        )
    if template_key == "threshold":
        return build_threshold_workout_steps(
            threshold_minutes=int(params.get("duration_minutes", 20)),
            warmup_minutes=int(params.get("warmup_minutes", 10)),
            cooldown_minutes=int(params.get("cooldown_minutes", 10)),
        )
    if template_key == "strides":
        return build_strides_workout_steps(
            count=int(params.get("count", 6)),
            stride_seconds=int(params.get("stride_seconds", 20)),
            recovery_seconds=int(params.get("recovery_seconds", 60)),
            warmup_minutes=int(params.get("warmup_minutes", 15)),
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
):
    steps = build_template_steps(template, params)
    return build_running_workout(name, steps, description=description)


def build_combined_workout(
    name: str,
    segments: List[Dict[str, Any]],
    description: Optional[str] = None,
):
    steps = combine_template_steps(segments)
    return build_running_workout(name, steps, description=description)


TEMPLATE_DESCRIPTIONS = {
    "easy": "Single continuous easy aerobic run in HR zone 2.",
    "long_run": "Extended easy aerobic run in HR zone 2.",
    "recovery": "Short recovery jog in HR zone 1.",
    "tempo": "Warmup, steady-state tempo block in HR zone 3, cooldown.",
    "threshold": "Warmup, lactate-threshold block in HR zone 4, cooldown.",
    "strides": "Easy warmup, short accelerations in HR zone 5 with easy recoveries, cooldown.",
    "sprint": "Warmup, short max-effort sprints in HR zone 5 with jog recoveries, cooldown.",
}
