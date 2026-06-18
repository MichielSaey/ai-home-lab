import sys
from datetime import date
from pathlib import Path

GARMIN_MCP_DIR = Path(__file__).resolve().parents[3] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))

from zones import (
    activity_date,
    easy_hard_from_zones,
    normalize_hr_zones,
    weekly_hr_zone_rows,
    weekly_stats_rows,
    zones_to_minute_columns,
)


def test_normalize_hr_zones_parses_zone_entries() -> None:
    raw = [
        {"zoneNumber": 1, "secsInZone": 120.0, "zoneLowBoundary": 100},
        {"zoneNumber": 2, "secsInZone": 300.5, "zoneLowBoundary": 120},
    ]
    assert normalize_hr_zones(raw) == {1: 120.0, 2: 300.5}


def test_normalize_hr_zones_handles_empty_and_invalid() -> None:
    assert normalize_hr_zones([]) == {}
    assert normalize_hr_zones(None) == {}
    assert normalize_hr_zones({"zoneNumber": 1}) == {}


def test_zones_to_minute_columns_returns_none_when_missing() -> None:
    assert zones_to_minute_columns({}) == [None, None, None, None, None]
    assert zones_to_minute_columns({1: 90, 3: 30}) == [1.5, 0.0, 0.5, 0.0, 0.0]


def test_easy_hard_from_zones_computes_80_20_split() -> None:
    zones = {1: 600, 2: 600, 3: 300, 4: 60, 5: 40}
    easy_min, hard_min, easy_pct = easy_hard_from_zones(zones)
    assert easy_min == 20.0
    assert hard_min == 6.67
    assert easy_pct == 75.0


def test_easy_hard_from_zones_returns_none_pct_without_data() -> None:
    easy_min, hard_min, easy_pct = easy_hard_from_zones({})
    assert easy_min == 0.0
    assert hard_min == 0.0
    assert easy_pct is None


def test_activity_date_parses_start_time_local() -> None:
    assert activity_date({"startTimeLocal": "2026-06-10 07:30:00"}) == date(2026, 6, 10)
    assert activity_date({}) is None
    assert activity_date({"startTimeLocal": "bad"}) is None


def test_weekly_stats_rows_combines_distance_and_zones() -> None:
    today = date(2026, 6, 17)
    activities = [
        {
            "activityId": 1,
            "distance": 5000,
            "startTimeLocal": "2026-06-16 07:00:00",
        }
    ]
    activity_zones = {1: {1: 600, 2: 0, 3: 0, 4: 0, 5: 0}}
    rows = weekly_stats_rows(activities, activity_zones, today, num_blocks=2)

    assert len(rows) == 2
    current_week = rows[1]
    assert current_week[2] == 5.0
    assert current_week[3] == 10.0


def test_weekly_hr_zone_rows_rolls_up_by_calendar_week() -> None:
    today = date(2026, 6, 17)
    dated_zones = [
        (date(2026, 6, 16), {1: 600, 2: 0, 3: 0, 4: 0, 5: 0}),
        (date(2026, 6, 10), {1: 0, 2: 0, 3: 1200, 4: 0, 5: 0}),
    ]
    rows = weekly_hr_zone_rows(dated_zones, today, num_blocks=2)

    assert len(rows) == 2
    current_week = rows[1]
    prior_week = rows[0]

    assert current_week[0] == "2026-06-11"
    assert current_week[1] == "2026-06-17"
    assert current_week[2:7] == [10.0, 0.0, 0.0, 0.0, 0.0]
    assert current_week[7:10] == [10.0, 0.0, 100.0]

    assert prior_week[0] == "2026-06-04"
    assert prior_week[1] == "2026-06-10"
    assert prior_week[2:7] == [0.0, 0.0, 20.0, 0.0, 0.0]
    assert prior_week[7:10] == [0.0, 20.0, 0.0]
