import sys
from pathlib import Path

import pytest

GARMIN_MCP_DIR = Path(__file__).resolve().parents[3] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))

from nutrition_matrix import (  # noqa: E402
    get_nutrition_cues,
    inject_nutrition_cues,
    nutrition_cue_steps,
    resolve_duration_bucket,
)
from workout_builder import build_workout_steps  # noqa: E402
from workout_templates import build_template_workout  # noqa: E402


@pytest.mark.parametrize(
    ("duration", "bucket"),
    [
        (30, "short"),
        (45, "medium"),
        (60, "medium"),
        (90, "long"),
        (150, "ultra"),
    ],
)
def test_resolve_duration_bucket(duration: int, bucket: str) -> None:
    assert resolve_duration_bucket(duration)["key"] == bucket


def test_get_nutrition_cues_returns_structured_phases() -> None:
    cues = get_nutrition_cues(60)

    assert cues["bucket"] == "medium"
    assert set(cues["before"]) == {"eat", "drink"}
    assert set(cues["during"]) == {"eat", "drink"}
    assert set(cues["after"]) == {"eat", "drink"}


def test_nutrition_cue_steps_include_phase_labels() -> None:
    steps = nutrition_cue_steps(90)
    assert len(steps) == 3
    assert all(step["type"] == "cue" for step in steps)
    assert steps[0]["message"].startswith("BEFORE")
    assert steps[1]["message"].startswith("DURING")
    assert steps[2]["message"].startswith("AFTER")


def test_inject_nutrition_cues_inserts_before_midpoint_and_after() -> None:
    base = [{"type": "interval", "duration_minutes": 20, "workout_type": "easy"}]
    injected = inject_nutrition_cues(base, 60)

    assert injected[0]["type"] == "cue"
    assert injected[-1]["type"] == "cue"
    assert injected[1]["type"] == "interval"


def test_build_workout_steps_supports_cue_type() -> None:
    steps = build_workout_steps(
        [
            {"type": "cue", "message": "Take gel now"},
            {"type": "interval", "duration_minutes": 10, "workout_type": "easy"},
        ]
    )

    cue = steps[0].model_dump()
    assert cue["stepType"]["stepTypeKey"] == "other"
    assert cue["description"] == "Take gel now"
    assert cue["endCondition"]["conditionTypeKey"] == "lap.button"


def test_build_template_workout_can_embed_nutrition_cues() -> None:
    workout = build_template_workout("Fuelled Easy", "easy", {"duration_minutes": 60}, include_nutrition_cues=True)
    step_types = [
        step.model_dump().get("stepType", {}).get("stepTypeKey")
        for step in workout.workoutSegments[0].workoutSteps
    ]
    assert step_types.count("other") == 3


def test_get_nutrition_cues_rejects_invalid_duration() -> None:
    with pytest.raises(ValueError, match="duration_minutes must be at least 1"):
        get_nutrition_cues(0)


def test_get_nutrition_cues_includes_intensity() -> None:
    cues = get_nutrition_cues(60, intensity="easy")
    assert cues["intensity"] == "easy"


def test_get_nutrition_cues_hard_intensity_adjusts_during_cues() -> None:
    easy = get_nutrition_cues(30, intensity="easy")
    hard = get_nutrition_cues(30, intensity="hard")
    assert hard["during"]["eat"] != easy["during"]["eat"]
    assert hard["during"]["drink"] != easy["during"]["drink"]


def test_get_nutrition_cues_rejects_invalid_intensity() -> None:
    with pytest.raises(ValueError, match="Unsupported intensity"):
        get_nutrition_cues(60, intensity="unknown")
