import pytest

from workout_templates import (
    TEMPLATE_TYPES,
    build_combined_workout,
    build_easy_workout_steps,
    build_sprint_workout_steps,
    build_strides_workout_steps,
    build_template_steps,
    build_template_workout,
    build_tempo_workout_steps,
    combine_template_steps,
)


def test_template_types_cover_all_named_templates() -> None:
    assert set(TEMPLATE_TYPES) == {
        "easy",
        "long_run",
        "recovery",
        "tempo",
        "threshold",
        "strides",
        "sprint",
    }


def test_build_easy_workout_steps_defaults_to_30_minutes() -> None:
    steps = build_easy_workout_steps(30)
    assert len(steps) == 1
    assert steps[0]["duration_minutes"] == 30
    assert steps[0]["workout_type"] == "easy"


def test_build_tempo_workout_steps_includes_warmup_and_cooldown() -> None:
    steps = build_tempo_workout_steps(tempo_minutes=20)
    assert [step["type"] for step in steps] == ["warmup", "interval", "cooldown"]
    assert steps[1]["workout_type"] == "tempo"


def test_build_strides_workout_steps_uses_repeat_block() -> None:
    steps = build_strides_workout_steps(count=4)
    assert steps[0]["type"] == "warmup"
    assert steps[1]["type"] == "repeat"
    assert steps[1]["iterations"] == 4
    assert len(steps[1]["steps"]) == 2
    assert steps[-1]["type"] == "cooldown"


def test_build_sprint_workout_steps_uses_repeat_block() -> None:
    steps = build_sprint_workout_steps(repetitions=3)
    assert steps[1]["type"] == "repeat"
    assert steps[1]["iterations"] == 3


def test_build_template_steps_applies_defaults() -> None:
    recovery_steps = build_template_steps("recovery")
    assert recovery_steps[0]["duration_minutes"] == 25

    long_run_steps = build_template_steps("long_run")
    assert long_run_steps[0]["duration_minutes"] == 90


def test_combine_template_steps_merges_named_templates() -> None:
    combined = combine_template_steps(
        [
            {"template": "easy", "params": {"duration_minutes": 20}},
            {"template": "recovery", "params": {"duration_minutes": 10}},
        ]
    )

    assert len(combined) == 2
    assert combined[0]["workout_type"] == "easy"
    assert combined[1]["workout_type"] == "recovery"


def test_combine_template_steps_accepts_explicit_step_segments() -> None:
    explicit = [{"type": "interval", "duration_minutes": 5, "workout_type": "easy"}]
    combined = combine_template_steps([{"steps": explicit}])
    assert combined == explicit


def test_build_template_workout_returns_running_workout() -> None:
    workout = build_template_workout("Tempo Tuesday", "tempo")
    assert workout.workoutName == "Tempo Tuesday"
    assert workout.estimatedDurationInSecs >= 60


def test_build_combined_workout_returns_running_workout() -> None:
    workout = build_combined_workout(
        "Easy + Strides",
        [
            {"template": "easy", "params": {"duration_minutes": 15}},
            {"template": "strides", "params": {"count": 4}},
        ],
    )
    assert workout.workoutName == "Easy + Strides"
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
