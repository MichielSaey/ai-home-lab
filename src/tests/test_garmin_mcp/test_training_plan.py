import sys
from datetime import date
from pathlib import Path

GARMIN_MCP_DIR = Path(__file__).resolve().parents[3] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))

from training_plan import (  # noqa: E402
    build_training_plan,
    classify_week_type,
    first_event_date,
)
from training_status import parse_training_status  # noqa: E402


def test_classify_week_type_recovery_on_week_four() -> None:
    assert classify_week_type(4, None) == "recovery"
    assert classify_week_type(3, None) == "build"


def test_classify_week_type_taper_overrides_recovery() -> None:
    assert classify_week_type(4, 2) == "taper_first"
    assert classify_week_type(4, 1) == "taper_final"


def test_first_event_date_picks_earliest_upcoming() -> None:
    today = date(2026, 6, 1)
    rows = [
        ["Half marathon", "event", "2026-08-01", None, None, None],
        ["10K", "event", "2026-07-01", None, None, None],
    ]
    assert first_event_date(rows, today=today) == date(2026, 7, 1)


def test_build_training_plan_includes_upcoming_week() -> None:
    stat_rows = [
        ["2026-05-05", "2026-05-11", 40.0, 0, 0, 0, 0, 0, 0, 0, 80.0],
        ["2026-05-12", "2026-05-18", 44.0, 0, 0, 0, 0, 0, 0, 0, 82.0],
        ["2026-05-19", "2026-05-25", 48.0, 0, 0, 0, 0, 0, 0, 0, 78.0],
        ["2026-05-26", "2026-06-01", 30.0, 0, 0, 0, 0, 0, 0, 0, 85.0],
    ]

    def load_at(_week_end: date) -> dict:
        return {"acute_load": 500, "chronic_load": 400, "acwr": None}

    plan = build_training_plan(stat_rows, event_date=None, load_at_week_end=load_at)

    assert len(plan) == 5
    assert plan[-2]["week_description"] == "current_week"
    assert plan[-1]["week_description"] == "upcoming_week"
    assert plan[-1]["actuals"]["distance_km"] is None
    assert plan[-1]["target"]["distance_km"] is not None


def test_parse_training_status_extracts_load() -> None:
    raw = {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "1": {
                    "primaryTrainingDevice": True,
                    "trainingStatusFeedbackPhrase": "PRODUCTIVE_3",
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": 600,
                        "dailyTrainingLoadChronic": 500,
                        "dailyAcuteChronicWorkloadRatio": 1.2,
                    },
                }
            }
        }
    }
    parsed = parse_training_status(raw)
    assert parsed["acute_load"] == 600
    assert parsed["chronic_load"] == 500
    assert parsed["acwr"] == 1.2
