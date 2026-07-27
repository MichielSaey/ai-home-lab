import pytest

from workout_builder import (
    build_running_workout,
    build_workout_steps,
    estimate_duration_seconds,
    extract_workout_id,
)


def test_build_running_workout_sets_name_and_duration() -> None:
    workout = build_running_workout(
        "Easy Run",
        [{"type": "interval", "duration_minutes": 30, "workout_type": "base"}],
        description="Morning jog",
    )

    assert workout.workoutName == "Easy Run"
    assert workout.description == "Morning jog"
    assert workout.estimatedDurationInSecs == 1800
    assert len(workout.workoutSegments) == 1
    assert len(workout.workoutSegments[0].workoutSteps) == 1


def test_build_workout_steps_supports_repeat_blocks() -> None:
    steps = build_workout_steps(
        [
            {
                "type": "repeat",
                "iterations": 3,
                "steps": [
                    {"type": "interval", "duration_minutes": 2, "workout_type": "threshold"},
                    {
                        "type": "recovery",
                        "duration_minutes": 1,
                        "workout_type": "interval_recovery",
                    },
                ],
            }
        ]
    )

    assert len(steps) == 1
    repeat = steps[0].model_dump()
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["numberOfIterations"] == 3
    assert len(repeat["workoutSteps"]) == 2


def test_build_workout_steps_distance_speed_sprint_effort() -> None:
    steps = build_workout_steps(
        [
            {
                "type": "interval",
                "distance_meters": 100,
                "target": "speed",
                "speed_mps_min": 5.5,
                "speed_mps_max": 6.5,
            }
        ]
    )
    payload = steps[0].model_dump()
    assert payload["endCondition"]["conditionTypeKey"] == "distance"
    assert payload["endConditionValue"] == 100.0
    assert payload["targetType"]["workoutTargetTypeKey"] == "speed.zone"
    assert payload["targetValueOne"] == 5.5
    assert payload["targetValueTwo"] == 6.5
    assert "zoneNumber" not in payload


def test_estimate_duration_seconds_counts_distance_speed_steps() -> None:
    steps = build_workout_steps(
        [
            {
                "type": "repeat",
                "iterations": 2,
                "steps": [
                    {
                        "type": "interval",
                        "distance_meters": 120,
                        "target": "speed",
                        "speed_mps_min": 6.0,
                        "speed_mps_max": 6.0,
                    },
                    {
                        "type": "recovery",
                        "duration_minutes": 0.5,
                        "workout_type": "interval_recovery",
                    },
                ],
            }
        ]
    )
    # 2 * (120m / 6 m/s + 30s) = 2 * (20 + 30) = 100
    assert estimate_duration_seconds(steps) == 100


def test_estimate_duration_seconds_counts_repeat_iterations() -> None:
    steps = build_workout_steps(
        [
            {
                "type": "repeat",
                "iterations": 2,
                "steps": [
                    {"type": "interval", "duration_minutes": 1, "workout_type": "threshold"},
                    {
                        "type": "recovery",
                        "duration_minutes": 0.5,
                        "workout_type": "interval_recovery",
                    },
                ],
            }
        ]
    )

    # 2 iterations * (60s + 30s)
    assert estimate_duration_seconds(steps) == 180


def test_extract_workout_id_handles_common_response_shapes() -> None:
    assert extract_workout_id({"workoutId": 101}) == 101
    assert extract_workout_id({"id": 202}) == 202
    assert extract_workout_id({"workout": {"workoutId": 303}}) == 303
    assert extract_workout_id({}) is None
    assert extract_workout_id("bad") is None


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([], "At least one workout step is required."),
        (
            [{"type": "interval", "workout_type": "base"}],
            "Each step requires duration_minutes or distance_meters.",
        ),
        (
            [
                {
                    "type": "interval",
                    "duration_minutes": 1,
                    "distance_meters": 100,
                    "workout_type": "base",
                }
            ],
            "duration_minutes or distance_meters, not both",
        ),
        (
            [
                {
                    "type": "interval",
                    "distance_meters": 100,
                    "workout_type": "sprint",
                }
            ],
            "require a speed target",
        ),
        (
            [{"type": "jog", "duration_minutes": 10}],
            "Unsupported step type 'jog'.",
        ),
        (
            [
                {
                    "type": "repeat",
                    "iterations": 0,
                    "steps": [
                        {"type": "interval", "duration_minutes": 1, "workout_type": "base"}
                    ],
                }
            ],
            "Repeat blocks require iterations >= 1.",
        ),
    ],
)
def test_build_workout_steps_validation_errors(steps, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_workout_steps(steps)
