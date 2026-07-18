from datetime import date, timedelta
from typing import Any, Callable, Optional

from weather import average_temp, days_in_range

# Polarized targets: medium (Zone 3) should always be ~0 — it is the gray zone
# to minimize. Hard work splits ~75%/25% into Z4 / Z5 (e.g. build 15/5).
# easy_pct + zone_4_pct + zone_5_pct ≈ 100 for every week type.
WEEK_TYPE_SPECS = {
    "build": {
        "multiplier": 1.10,
        "easy_pct": 80,
        "medium_pct": 0,
        "zone_4_pct": 15,
        "zone_5_pct": 5,
        "ref": "prev",
    },
    # Recovery volume is 80% of peak build-week km, not the prior partial week.
    "recovery": {
        "multiplier": 0.80,
        "easy_pct": 90,
        "medium_pct": 0,
        "zone_4_pct": 8,
        "zone_5_pct": 2,
        "ref": "peak",
    },
    "taper_first": {
        "multiplier": 0.80,
        "easy_pct": 80,
        "medium_pct": 0,
        "zone_4_pct": 15,
        "zone_5_pct": 5,
        "ref": "peak",
    },
    "taper_final": {
        "multiplier": 0.64,
        "easy_pct": 85,
        "medium_pct": 0,
        "zone_4_pct": 11,
        "zone_5_pct": 4,
        "ref": "peak",
    },
    "race": {
        "multiplier": 0.30,
        "easy_pct": 90,
        "medium_pct": 0,
        "zone_4_pct": 8,
        "zone_5_pct": 2,
        "ref": "prev",
    },
}


def weeks_until_event(from_date: date, event_date: date) -> int | None:
    """Whole weeks from ``from_date`` until ``event_date``.

    Returns ``None`` when the event is already in the past relative to
    ``from_date`` so we do not label post-race weeks as ``race`` / taper.
    """
    if event_date < from_date:
        return None
    return (event_date - from_date).days // 7


def classify_week_type(
    week_number: int,
    weeks_until: int | None,
    *,
    schedule_recovery: bool = False,
) -> str:
    if weeks_until is not None:
        if weeks_until == 0:
            return "race"
        if weeks_until == 1:
            return "taper_final"
        if weeks_until == 2:
            return "taper_first"
    if schedule_recovery and week_number % 4 == 0:
        return "recovery"
    return "build"


def _week_contains(week_start: date, week_end: date, event_date: date) -> bool:
    return week_start <= event_date <= week_end


def _is_recovery_week_after_event(
    week_start: date, week_end: date, event_date: date
) -> bool:
    """True when this week is the first recovery week after a past event."""
    if event_date >= week_end:
        return False
    recovery_end = event_date + timedelta(days=7)
    return week_start <= recovery_end and week_end > event_date


def classify_plan_week(
    week_start: date,
    week_end: date,
    week_number: int,
    upcoming_event_date: date | None,
    last_event_date: date | None,
    *,
    is_current: bool = False,
    schedule_recovery: bool = False,
    today: date | None = None,
) -> str:
    """Week type for one plan row, including post-race recovery."""
    today = today or date.today()
    if last_event_date is not None:
        if _week_contains(week_start, week_end, last_event_date) and not is_current:
            return "race"
        if is_current and last_event_date <= today and (today - last_event_date).days < 7:
            return "recovery"
        if last_event_date < week_end and _is_recovery_week_after_event(
            week_start, week_end, last_event_date
        ):
            return "recovery"
    weeks_until = (
        weeks_until_event(week_end, upcoming_event_date)
        if upcoming_event_date
        else None
    )
    return classify_week_type(
        week_number, weeks_until, schedule_recovery=schedule_recovery
    )


def _event_date_from_row(row: list[Any]) -> date | None:
    try:
        return date.fromisoformat(row[2])
    except (ValueError, IndexError, TypeError):
        return None


def _event_summary_row(row: list[Any]) -> dict[str, Any]:
    event_date = _event_date_from_row(row)
    return {
        "title": row[0],
        "date": event_date.isoformat() if event_date else row[2],
        "target_value": row[3] if len(row) > 3 else None,
        "target_unit": row[4] if len(row) > 4 else None,
    }


def latest_event_within_days(
    event_rows: list[list[Any]],
    *,
    today: date | None = None,
    days: int = 28,
) -> dict[str, Any] | None:
    """Most recent event that occurred within the last ``days`` (default 4 weeks)."""
    today = today or date.today()
    cutoff = today - timedelta(days=days)
    latest: tuple[date, list[Any]] | None = None
    for row in event_rows:
        event_date = _event_date_from_row(row)
        if event_date is None or event_date >= today or event_date < cutoff:
            continue
        if latest is None or event_date > latest[0]:
            latest = (event_date, row)
    return _event_summary_row(latest[1]) if latest else None


def first_event_date(event_rows: list[list[Any]], today: date | None = None) -> date | None:
    """Earliest upcoming event — used for taper/race week typing."""
    today = today or date.today()
    upcoming: list[date] = []
    for row in event_rows:
        event_date = _event_date_from_row(row)
        if event_date is not None and event_date > today:
            upcoming.append(event_date)
    return min(upcoming) if upcoming else None


def last_event_date_from_payload(events: dict[str, Any]) -> date | None:
    """Parse ``latest_event`` from a ``get_events`` response."""
    latest = events.get("latest_event")
    if not isinstance(latest, dict):
        return None
    try:
        return date.fromisoformat(str(latest.get("date"))[:10])
    except (ValueError, TypeError):
        return None


def round_km(km: float | None) -> int | None:
    return round(km) if km is not None else None


def calc_distance_target(
    week_type: str, prev_km: float | None, peak_km: float
) -> int | None:
    spec = WEEK_TYPE_SPECS[week_type]
    if week_type == "build":
        if not prev_km:
            return None
        return round_km(prev_km * spec["multiplier"])
    base = peak_km if spec["ref"] == "peak" else (prev_km or 0)
    if base <= 0:
        return None
    return round_km(base * spec["multiplier"])


def build_target(
    week_type: str, prev_km: float | None, peak_km: float
) -> dict[str, Any]:
    spec = WEEK_TYPE_SPECS[week_type]
    zone_4_pct = spec["zone_4_pct"]
    zone_5_pct = spec["zone_5_pct"]
    return {
        "distance_km": calc_distance_target(week_type, prev_km, peak_km),
        "easy_pct": spec["easy_pct"],
        "medium_pct": spec["medium_pct"],
        "zone_4_pct": zone_4_pct,
        "zone_5_pct": zone_5_pct,
        # Convenience: combined hard = Z4 + Z5
        "hard_pct": zone_4_pct + zone_5_pct,
    }


def calc_acwr(acute: Any, chronic: Any) -> float | None:
    if acute is None or chronic is None or chronic == 0:
        return None
    return round(float(acute) / float(chronic), 2)


def actuals_from_stat_row(row: list[Any], load: dict[str, Any]) -> dict[str, Any]:
    # Row layout (weekly_stats_rows):
    #   0 start, 1 end, 2 distance_km, 3 total_zone_min,
    #   4..8 z1..z5,
    #   9 easy_min, 10 medium_min, 11 hard_min,
    #   12 easy_pct, 13 medium_pct, 14 hard_pct, 15 zone_4_pct, 16 zone_5_pct
    acute = load.get("acute_load")
    chronic = load.get("chronic_load")
    return {
        "distance_km": row[2],
        "total_zone_min": row[3],
        "zone_1_min": row[4],
        "zone_2_min": row[5],
        "zone_3_min": row[6],
        "zone_4_min": row[7],
        "zone_5_min": row[8],
        "easy_pct": row[12],
        "medium_pct": row[13],
        "hard_pct": row[14],
        "zone_4_pct": row[15],
        "zone_5_pct": row[16],
        "acute_load": acute,
        "chronic_load": chronic,
        "acwr": calc_acwr(acute, chronic),
    }


def empty_actuals() -> dict[str, Any]:
    return {
        "distance_km": None,
        "total_zone_min": None,
        "zone_1_min": None,
        "zone_2_min": None,
        "zone_3_min": None,
        "zone_4_min": None,
        "zone_5_min": None,
        "easy_pct": None,
        "medium_pct": None,
        "hard_pct": None,
        "zone_4_pct": None,
        "zone_5_pct": None,
        "acute_load": None,
        "chronic_load": None,
        "acwr": None,
    }


def _enrich_week_weather(
    block: dict[str, Any],
    start: date,
    end: date,
    daily_weather: Optional[dict[str, dict[str, Any]]],
    include_days: bool,
) -> None:
    """Attach avg_temp_c (and per-day blocks when include_days) to a plan week.

    No-op when daily_weather is None, so weather stays purely additive.
    """
    if daily_weather is None:
        return
    block["avg_temp_c"] = average_temp(daily_weather, start, end)
    if include_days:
        block["days"] = days_in_range(daily_weather, start, end)


def build_training_plan(
    stat_rows: list[list[Any]],
    event_date: date | None,
    load_at_week_end: Callable[[date], dict[str, Any]],
    daily_weather: Optional[dict[str, dict[str, Any]]] = None,
    last_event_date: date | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    if not stat_rows:
        return []

    today = today or date.today()
    week_types: list[str] = []
    for i, row in enumerate(stat_rows):
        week_start = date.fromisoformat(row[0])
        week_end = date.fromisoformat(row[1])
        is_latest = i == len(stat_rows) - 1
        week_types.append(
            classify_plan_week(
                week_start,
                week_end,
                i + 1,
                event_date,
                last_event_date,
                is_current=is_latest,
                schedule_recovery=False,
                today=today,
            )
        )

    peak_km = max(
        (float(row[2] or 0) for row, wt in zip(stat_rows, week_types) if wt == "build"),
        default=max((float(row[2] or 0) for row in stat_rows), default=0),
    )

    training_plan: list[dict[str, Any]] = []
    prev_km: float | None = None

    for i, row in enumerate(stat_rows):
        week_start = date.fromisoformat(row[0])
        week_end = date.fromisoformat(row[1])
        week_type = week_types[i]
        is_latest = i == len(stat_rows) - 1
        load = load_at_week_end(week_end)

        block = {
            "week_description": "latest_week" if is_latest else "past_week",
            "week_type": week_type,
            "actuals": actuals_from_stat_row(row, load),
            "target": build_target(week_type, prev_km, peak_km),
        }
        # Latest rolling block gets per-day weather for context; past blocks avg only.
        _enrich_week_weather(
            block, week_start, week_end, daily_weather, include_days=is_latest
        )
        training_plan.append(block)
        prev_km = float(row[2] or 0) or prev_km

    last_end = date.fromisoformat(stat_rows[-1][1])
    # Upcoming plan: next 7 days starting the day after the latest rolling block ends.
    plan_start = last_end + timedelta(days=1)
    plan_week_num = len(stat_rows) + 1
    plan_end = plan_start + timedelta(days=6)
    plan_type = classify_plan_week(
        plan_start,
        plan_end,
        plan_week_num,
        event_date,
        last_event_date,
        is_current=True,
        schedule_recovery=True,
        today=today,
    )

    upcoming_block = {
        "week_description": "upcoming_week",
        "week_type": plan_type,
        "actuals": empty_actuals(),
        "target": build_target(plan_type, prev_km, peak_km),
    }
    # Upcoming week always gets a 7-day scaffold (dates for the agent). Weather
    # fields are filled when GARMIN_HOME_LAT/LON are configured.
    if daily_weather is not None:
        upcoming_block["avg_temp_c"] = average_temp(daily_weather, plan_start, plan_end)
    upcoming_block["days"] = days_in_range(daily_weather or {}, plan_start, plan_end)
    training_plan.append(upcoming_block)

    return training_plan
