from datetime import date

from training_plan import (
    WEEK_TYPE_SPECS,
    build_target,
    build_training_plan,
    classify_plan_week,
    classify_week_type,
    first_event_date,
    latest_event_within_days,
    weeks_until_event,
)
from training_status import parse_training_status


def _stat_row(
    start: str,
    end: str,
    distance: float,
    *,
    easy_pct: float = 80.0,
    medium_pct: float = 0.0,
    hard_pct: float = 20.0,
    zone_4_pct: float = 15.0,
    zone_5_pct: float = 5.0,
    total_zone_min: float = 0.0,
) -> list:
    # Layout: start, end, distance_km, total_zone_min, z1..z5,
    # easy_min, medium_min, hard_min, easy_pct, medium_pct, hard_pct,
    # zone_4_pct, zone_5_pct
    return [
        start,
        end,
        distance,
        total_zone_min,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        easy_pct,
        medium_pct,
        hard_pct,
        zone_4_pct,
        zone_5_pct,
    ]


def test_classify_week_type_recovery_only_when_scheduled() -> None:
    assert classify_week_type(4, None, schedule_recovery=False) == "build"
    assert classify_week_type(4, None, schedule_recovery=True) == "recovery"
    assert classify_week_type(3, None, schedule_recovery=True) == "build"


def test_classify_week_type_taper_overrides_recovery() -> None:
    assert classify_week_type(4, 2, schedule_recovery=True) == "taper_first"
    assert classify_week_type(4, 1, schedule_recovery=True) == "taper_final"


def test_weeks_until_event_none_when_event_in_past() -> None:
    assert weeks_until_event(date(2026, 6, 10), date(2026, 6, 1)) is None
    assert weeks_until_event(date(2026, 6, 1), date(2026, 8, 1)) == 8


def test_first_event_date_picks_earliest_upcoming() -> None:
    today = date(2026, 6, 1)
    rows = [
        ["Half marathon", "event", "2026-08-01", None, None, None],
        ["10K", "event", "2026-07-01", None, None, None],
    ]
    assert first_event_date(rows, today=today) == date(2026, 7, 1)


def test_latest_event_within_four_weeks() -> None:
    today = date(2026, 6, 15)
    rows = [
        ["Old race", "event", "2026-04-01", 10, "km", None],
        ["Spring 10K", "event", "2026-05-20", 10, "km", None],
        ["UTDS 42", "event", "2026-08-22", 42, "km", None],
    ]
    latest = latest_event_within_days(rows, today=today, days=28)
    assert latest is not None
    assert latest["title"] == "Spring 10K"
    assert latest["target_value"] == 10
    assert latest["target_unit"] == "km"


def test_latest_event_ignores_upcoming() -> None:
    today = date(2026, 6, 1)
    rows = [["Future race", "event", "2026-08-01", 42, "km", None]]
    assert latest_event_within_days(rows, today=today) is None


def test_current_week_recovery_within_seven_days_of_race() -> None:
    today = date(2026, 6, 5)
    race_day = date(2026, 6, 1)
    week_start = date(2026, 6, 2)
    week_end = date(2026, 6, 8)
    assert (
        classify_plan_week(
            week_start,
            week_end,
            4,
            upcoming_event_date=None,
            last_event_date=race_day,
            is_current=True,
            today=today,
        )
        == "recovery"
    )


def test_past_race_week_labeled_race_not_recovery() -> None:
    race_day = date(2026, 5, 10)
    week_start = date(2026, 5, 5)
    week_end = date(2026, 5, 11)
    assert (
        classify_plan_week(
            week_start,
            week_end,
            2,
            upcoming_event_date=None,
            last_event_date=race_day,
            is_current=False,
            today=date(2026, 6, 1),
        )
        == "race"
    )


def test_week_type_specs_use_80_15_5_hard_split() -> None:
    build = WEEK_TYPE_SPECS["build"]
    assert build["easy_pct"] == 80
    assert build["medium_pct"] == 0
    assert build["zone_4_pct"] == 15
    assert build["zone_5_pct"] == 5
    recovery = WEEK_TYPE_SPECS["recovery"]
    assert recovery["zone_4_pct"] == 8
    assert recovery["zone_5_pct"] == 2


def test_build_target_includes_zone_pcts() -> None:
    target = build_target("build", prev_km=40, peak_km=48)
    assert target["easy_pct"] == 80
    assert target["zone_4_pct"] == 15
    assert target["zone_5_pct"] == 5
    assert target["hard_pct"] == 20


def test_build_training_plan_latest_week_recovery_after_recent_race() -> None:
    today = date(2026, 6, 5)
    stat_rows = [
        _stat_row("2026-05-05", "2026-05-11", 40.0),
        _stat_row("2026-05-12", "2026-05-18", 44.0, easy_pct=82.0, hard_pct=18.0),
        _stat_row("2026-05-19", "2026-05-25", 48.0, easy_pct=78.0, hard_pct=22.0),
        _stat_row("2026-05-26", "2026-06-01", 30.0, easy_pct=85.0, hard_pct=15.0),
    ]
    plan = build_training_plan(
        stat_rows,
        event_date=None,
        load_at_week_end=lambda _e: {},
        last_event_date=date(2026, 6, 1),
        today=today,
    )
    assert plan[-2]["week_description"] == "latest_week"
    assert plan[-2]["week_type"] == "recovery"
    assert plan[-2]["target"]["easy_pct"] == 90
    assert plan[-2]["target"]["zone_4_pct"] == 8
    assert plan[-2]["target"]["zone_5_pct"] == 2
    # Recovery upcoming week: 80% of peak build week (48 km) ≈ 38 km
    assert plan[-1]["week_type"] == "recovery"
    assert plan[-1]["target"]["distance_km"] == 38


def test_build_training_plan_includes_upcoming_week() -> None:
    stat_rows = [
        _stat_row("2026-05-05", "2026-05-11", 40.0),
        _stat_row("2026-05-12", "2026-05-18", 44.0, easy_pct=82.0, hard_pct=18.0),
        _stat_row("2026-05-19", "2026-05-25", 48.0, easy_pct=78.0, hard_pct=22.0),
        _stat_row("2026-05-26", "2026-06-01", 30.0, easy_pct=85.0, hard_pct=15.0),
    ]

    def load_at(_week_end: date) -> dict:
        return {"acute_load": 500, "chronic_load": 400, "acwr": None}

    plan = build_training_plan(stat_rows, event_date=None, load_at_week_end=load_at)

    assert len(plan) == 5
    assert plan[-2]["week_description"] == "latest_week"
    assert plan[-1]["week_description"] == "upcoming_week"
    # Lookback rows are not retroactively labeled recovery without an event taper.
    assert plan[3]["week_type"] == "build"
    assert plan[-1]["actuals"]["distance_km"] is None
    assert plan[-1]["actuals"]["total_zone_min"] is None
    assert plan[-1]["target"]["distance_km"] is not None
    assert plan[0]["actuals"]["medium_pct"] == 0.0
    assert plan[0]["actuals"]["hard_pct"] == 20.0
    assert plan[0]["actuals"]["zone_4_pct"] == 15.0
    assert plan[0]["actuals"]["zone_5_pct"] == 5.0
    assert plan[-1]["target"]["medium_pct"] == 0
    assert plan[-1]["target"]["zone_4_pct"] == 15
    assert plan[-1]["target"]["zone_5_pct"] == 5


def test_build_training_plan_enriches_weather() -> None:
    stat_rows = [
        _stat_row("2026-05-26", "2026-06-01", 40.0),
        _stat_row("2026-06-02", "2026-06-08", 44.0, easy_pct=82.0, hard_pct=18.0),
    ]

    def load_at(_week_end: date) -> dict:
        return {}

    daily_weather = {
        "2026-05-26": {"temp_c": 20.0, "weather_code": 0, "description": "Clear sky"},
        "2026-05-27": {"temp_c": 22.0, "weather_code": 3, "description": "Overcast"},
        "2026-06-02": {"temp_c": 30.0, "weather_code": 0, "description": "Clear sky"},
        "2026-06-08": {"temp_c": 34.0, "weather_code": 0, "description": "Clear sky"},
    }

    plan = build_training_plan(
        stat_rows, event_date=None, load_at_week_end=load_at, daily_weather=daily_weather
    )

    past_week = plan[0]
    latest_week = plan[1]
    upcoming_week = plan[2]

    assert past_week["week_description"] == "past_week"
    assert past_week["avg_temp_c"] == 21.0
    assert "days" not in past_week

    assert latest_week["week_description"] == "latest_week"
    assert latest_week["avg_temp_c"] == 32.0
    assert [d["date"] for d in latest_week["days"]] == [
        "2026-06-02",
        "2026-06-03",
        "2026-06-04",
        "2026-06-05",
        "2026-06-06",
        "2026-06-07",
        "2026-06-08",
    ]
    assert latest_week["days"][0]["weather"] == "Clear sky"

    assert upcoming_week["week_description"] == "upcoming_week"
    assert "days" in upcoming_week


def test_build_training_plan_omits_weather_when_none() -> None:
    stat_rows = [
        _stat_row("2026-05-26", "2026-06-01", 40.0),
    ]

    plan = build_training_plan(
        stat_rows, event_date=None, load_at_week_end=lambda _e: {}
    )

    past_week = plan[0]
    upcoming_week = plan[1]
    assert "avg_temp_c" not in past_week
    assert "days" not in past_week
    assert "avg_temp_c" not in upcoming_week
    assert [day["date"] for day in upcoming_week["days"]] == [
        "2026-06-02",
        "2026-06-03",
        "2026-06-04",
        "2026-06-05",
        "2026-06-06",
        "2026-06-07",
        "2026-06-08",
    ]
    assert all(day["avg_temp_c"] is None for day in upcoming_week["days"])


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
