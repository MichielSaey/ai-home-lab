from datetime import date

from zones import (
    activity_date,
    intensity_split_from_zones,
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


def test_intensity_split_separates_medium_gray_zone() -> None:
    zones = {1: 600, 2: 600, 3: 300, 4: 60, 5: 40}
    (
        easy_min,
        medium_min,
        hard_min,
        easy_pct,
        medium_pct,
        hard_pct,
        zone_4_pct,
        zone_5_pct,
    ) = intensity_split_from_zones(zones)
    assert easy_min == 20.0
    assert medium_min == 5.0
    assert hard_min == 1.67
    # Percentages span all tracked time (Z1-5) and sum to 100.
    assert easy_pct == 75.0
    assert medium_pct == 18.8
    assert hard_pct == 6.2
    assert zone_4_pct == 3.8
    assert zone_5_pct == 2.5


def test_intensity_split_returns_none_pct_without_data() -> None:
    (
        easy_min,
        medium_min,
        hard_min,
        easy_pct,
        medium_pct,
        hard_pct,
        zone_4_pct,
        zone_5_pct,
    ) = intensity_split_from_zones({})
    assert easy_min == 0.0
    assert medium_min == 0.0
    assert hard_min == 0.0
    assert easy_pct is None
    assert medium_pct is None
    assert hard_pct is None
    assert zone_4_pct is None
    assert zone_5_pct is None


def test_activity_date_parses_start_time_local() -> None:
    assert activity_date({"startTimeLocal": "2026-06-10 07:30:00"}) == date(2026, 6, 10)
    assert activity_date({}) is None
    assert activity_date({"startTimeLocal": "bad"}) is None


def test_weekly_stats_rows_combines_distance_and_zones() -> None:
    anchor_end = date(2026, 6, 16)
    activities = [
        {
            "activityId": 1,
            "distance": 5000,
            "startTimeLocal": "2026-06-16 07:00:00",
        }
    ]
    activity_zones = {1: {1: 600, 2: 0, 3: 0, 4: 0, 5: 0}}
    rows = weekly_stats_rows(activities, activity_zones, anchor_end, num_blocks=2)

    assert len(rows) == 2
    latest_week = rows[1]
    # start, end, distance_km, total_zone_min, z1..
    assert latest_week[0] == "2026-06-10"
    assert latest_week[1] == "2026-06-16"
    assert latest_week[2] == 5.0
    assert latest_week[3] == 10.0
    assert latest_week[4] == 10.0


def test_weekly_stats_rows_includes_non_running_activities() -> None:
    anchor_end = date(2026, 6, 16)
    activities = [
        {
            "activityId": 1,
            "distance": 20000,
            "activityType": {"typeKey": "cycling"},
            "startTimeLocal": "2026-06-16 07:00:00",
        },
        {
            "activityId": 2,
            "distance": 0,
            "activityType": {"typeKey": "strength_training"},
            "startTimeLocal": "2026-06-15 18:00:00",
        },
    ]
    activity_zones = {
        1: {1: 0, 2: 1800, 3: 0, 4: 600, 5: 0},
        2: {1: 300, 2: 900, 3: 0, 4: 0, 5: 0},
    }
    rows = weekly_stats_rows(activities, activity_zones, anchor_end, num_blocks=1)
    latest = rows[0]
    assert latest[2] == 20.0  # cycling distance only
    assert latest[3] == 60.0  # (1800+600+300+900)/60
    assert latest[5] == 45.0  # z2 minutes


def test_weekly_hr_zone_rows_rolls_up_by_rolling_block() -> None:
    anchor_end = date(2026, 6, 16)
    dated_zones = [
        (date(2026, 6, 16), {1: 600, 2: 0, 3: 0, 4: 0, 5: 0}),
        (date(2026, 6, 10), {1: 0, 2: 0, 3: 1200, 4: 0, 5: 0}),
    ]
    rows = weekly_hr_zone_rows(dated_zones, anchor_end, num_blocks=2)

    assert len(rows) == 2
    latest_week = rows[1]
    prior_week = rows[0]

    # start, end, total_zone_min, z1..z5, easy/medium/hard min, pcts, z4/z5 pct
    assert latest_week[0] == "2026-06-10"
    assert latest_week[1] == "2026-06-16"
    assert latest_week[2] == 30.0
    assert latest_week[3:8] == [10.0, 0.0, 20.0, 0.0, 0.0]
    # easy_min, medium_min, hard_min
    assert latest_week[8:11] == [10.0, 20.0, 0.0]
    # easy_pct, medium_pct, hard_pct
    assert latest_week[11:14] == [33.3, 66.7, 0.0]
    assert latest_week[14:16] == [0.0, 0.0]

    assert prior_week[0] == "2026-06-03"
    assert prior_week[1] == "2026-06-09"
    assert prior_week[2] == 0.0
    assert prior_week[3:8] == [0.0, 0.0, 0.0, 0.0, 0.0]
