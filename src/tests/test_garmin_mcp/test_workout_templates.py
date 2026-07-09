import pytest

from workout_templates import (
    TEMPLATE_ALIASES,
    TEMPLATE_TYPES,
    build_base_workout_steps,
    build_combined_workout,
    build_sprint_workout_steps,
    build_threshold_workout_steps,
    build_template_steps,
    build_template_workout,
    combine_template_steps,
)


def test_template_types_cover_all_named_templates() -> None:
    assert set(TEMPLATE_TYPES) == {
        "base",
        "long_run",
        "recovery",
        "threshold",
        "sprint",
        "hill_repeats",
        "weighted_pack",
    }


def test_build_base_workout_steps_defaults_to_30_minutes() -> None:
    steps = build_base_workout_steps(30)
    assert len(steps) == 1
    assert steps[0]["duration_minutes"] == 30
    assert steps[0]["workout_type"] == "base"


def test_build_sprint_workout_steps_uses_repeat_block() -> None:
    steps = build_sprint_workout_steps(repetitions=3)
    assert steps[1]["type"] == "repeat"
    assert steps[1]["iterations"] == 3


def test_build_threshold_workout_steps_uses_repeat_block() -> None:
    steps = build_threshold_workout_steps(repetitions=5, interval_minutes=4)
    assert steps[1]["type"] == "repeat"
    assert steps[1]["iterations"] == 5
    assert steps[1]["steps"][0]["workout_type"] == "threshold"
    assert steps[1]["steps"][0]["duration_minutes"] == 4
    assert steps[1]["steps"][1]["duration_minutes"] == 2


def test_build_threshold_workout_steps_default_recovery() -> None:
    steps = build_threshold_workout_steps()
    assert steps[1]["steps"][1]["duration_minutes"] == 2


def test_hill_repeats_alias_matches_sprint_structure() -> None:
    assert TEMPLATE_ALIASES["hill_repeats"] == "sprint"
    hill = build_template_steps("hill_repeats", {"repetitions": 4})
    sprint = build_template_steps("sprint", {"repetitions": 4})
    assert hill == sprint
    assert hill[1]["type"] == "repeat"
    assert hill[1]["iterations"] == 4


def test_weighted_pack_alias_matches_base_structure() -> None:
    assert TEMPLATE_ALIASES["weighted_pack"] == "base"
    pack = build_template_steps("weighted_pack", {"duration_minutes": 45})
    base = build_template_steps("base", {"duration_minutes": 45})
    assert pack == base
    assert pack[0]["workout_type"] == "base"


def test_build_template_steps_applies_defaults() -> None:
    recovery_steps = build_template_steps("recovery")
    assert recovery_steps[0]["duration_minutes"] == 25

    long_run_steps = build_template_steps("long_run")
    assert long_run_steps[0]["duration_minutes"] == 90


def test_combine_template_steps_merges_named_templates() -> None:
    combined = combine_template_steps(
        [
            {"template": "base", "params": {"duration_minutes": 20}},
            {"template": "recovery", "params": {"duration_minutes": 10}},
        ]
    )

    assert len(combined) == 2
    assert combined[0]["workout_type"] == "base"
    assert combined[1]["workout_type"] == "recovery"


def test_combine_template_steps_accepts_explicit_step_segments() -> None:
    explicit = [{"type": "interval", "duration_minutes": 5, "workout_type": "base"}]
    combined = combine_template_steps([{"steps": explicit}])
    assert combined == explicit


def test_build_template_workout_returns_running_workout() -> None:
    workout = build_template_workout("Threshold Tuesday", "threshold")
    assert workout.workoutName == "Threshold Tuesday"
    assert workout.estimatedDurationInSecs >= 60


def test_build_combined_workout_returns_running_workout() -> None:
    workout = build_combined_workout(
        "Base + Sprints",
        [
            {"template": "base", "params": {"duration_minutes": 15}},
            {"template": "sprint", "params": {"repetitions": 4}},
        ],
    )
    assert workout.workoutName == "Base + Sprints"
    assert workout.estimatedDurationInSecs > 60


@pytest.mark.parametrize(
    ("segments", "message"),
    [
        ([], "Provide at least one template segment to combine."),
        ([{"params": {"duration_minutes": 10}}], "Each segment needs 'template' or explicit 'steps'."),
    ],
)
def test_combine_template_steps_validation_errors(segments, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        combine_template_steps(segments)


def test_build_template_steps_rejects_unknown_template() -> None:
    with pytest.raises(ValueError, match="Unknown template 'fartlek'"):
        build_template_steps("fartlek")
