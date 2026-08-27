from datetime import date, timedelta
from statistics import median
from typing import Any, Callable, Optional

from weather import average_temp, days_in_range

# Polarized targets: medium (Zone 3) should always be ~0 — it is the gray zone
# to minimize. Hard work splits ~75%/25% into Z4 / Z5 (e.g. build 15/5).
# easy_pct + zone_4_pct + zone_5_pct ≈ 100 for every week type.
# Volume multipliers apply to chronic/peak *minutes*, not km.
WEEK_TYPE_SPECS = {
    "build": {
        "multiplier": 1.15,
        "easy_pct": 80,
        "medium_pct": 0,
        "zone_4_pct": 15,
        "zone_5_pct": 5,
        "ref": "chronic",
    },
    "recovery": {
        "multiplier": 0.80,
        "easy_pct": 90,
        "medium_pct": 0,
        "zone_4_pct": 8,
        "zone_5_pct": 2,
        "ref": "chronic",
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
        "ref": "peak",
    },
}

OUTLIER_BAND = 0.50
HOT_TEMP_C = 28.0

RACE_PEAK_MINUTES = {
    "5k": 240,
    "10k": 300,
    "half": 400,
    "marathon": 520,
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


def first_event_title(
    event_rows: list[list[Any]], today: date | None = None
) -> str | None:
    """Title of the earliest upcoming event (for race peak heuristics)."""
    today = today or date.today()
    best: tuple[date, str] | None = None
    for row in event_rows:
        event_date = _event_date_from_row(row)
        if event_date is None or event_date <= today:
            continue
        title = str(row[0]) if row else ""
        if best is None or event_date < best[0]:
            best = (event_date, title)
    return best[1] if best else None


def last_event_date_from_payload(events: dict[str, Any]) -> date | None:
    """Parse ``latest_event`` from a ``get_events`` response."""
    latest = events.get("latest_event")
    if not isinstance(latest, dict):
        return None
    try:
        return date.fromisoformat(str(latest.get("date"))[:10])
    except (ValueError, TypeError):
        return None


def round_minutes(value: float | None) -> int | None:
    return round(value) if value is not None else None


def goal_peak_minutes_from_title(
    title: str | None,
    chronic_min: float | None,
    peak_min: float,
) -> float:
    """Map event title heuristics to a goal peak weekly minutes value."""
    text = (title or "").lower()
    # Check half before marathon so "Half Marathon" does not map to full.
    if "half" in text or "21.1" in text or "21k" in text:
        return float(RACE_PEAK_MINUTES["half"])
    if "marathon" in text or "42" in text:
        return float(RACE_PEAK_MINUTES["marathon"])
    if "10k" in text or "10 k" in text:
        return float(RACE_PEAK_MINUTES["10k"])
    if "5k" in text or "5 k" in text:
        return float(RACE_PEAK_MINUTES["5k"])
    base = chronic_min if chronic_min is not None else 0.0
    return float(max(base, peak_min))


def chronic_minutes_from_rows(
    stat_rows: list[list[Any]],
) -> tuple[float | None, list[dict[str, Any]]]:
    """Chronic weekly minutes from lookback rows: median, drop 50% outliers, mean."""
    samples: list[tuple[str, str, float]] = []
    for row in stat_rows[-4:]:
        try:
            minutes = float(row[3] or 0)
        except (TypeError, ValueError, IndexError):
            continue
        if minutes <= 0:
            continue
        samples.append((str(row[0]), str(row[1]), minutes))

    if not samples:
        return None, []

    values = [m for _, _, m in samples]
    mid = float(median(values))
    if mid <= 0:
        return None, []

    kept: list[float] = []
    dropped: list[dict[str, Any]] = []
    for start, end, minutes in samples:
        if abs(minutes - mid) / mid > OUTLIER_BAND:
            dropped.append(
                {"start": start, "end": end, "total_zone_min": round(minutes, 2)}
            )
        else:
            kept.append(minutes)

    if not kept:
        return mid, dropped
    return sum(kept) / len(kept), dropped


def calc_volume_target(
    week_type: str,
    chronic_min: float | None,
    peak_min: float,
    *,
    weeks_until: int | None = None,
    goal_peak_min: float | None = None,
) -> int | None:
    """Weekly training-time target in minutes for a week type."""
    spec = WEEK_TYPE_SPECS[week_type]
    multiplier = float(spec["multiplier"])

    if week_type in ("build", "recovery"):
        if chronic_min is None or chronic_min <= 0:
            return None
        if (
            week_type == "build"
            and goal_peak_min is not None
            and weeks_until is not None
            and weeks_until > 2
        ):
            if goal_peak_min <= chronic_min:
                return round_minutes(chronic_min * multiplier)
            build_weeks = max(weeks_until - 2, 1)
            step = chronic_min + (goal_peak_min - chronic_min) / build_weeks
            return round_minutes(min(chronic_min * multiplier, step))
        return round_minutes(chronic_min * multiplier)

    base = peak_min if peak_min > 0 else (chronic_min or 0)
    if base <= 0:
        return None
    return round_minutes(base * multiplier)


def calc_distance_target(
    week_type: str, prev_km: float | None, peak_km: float
) -> int | None:
    """Backward-compatible alias — prefers chronic/peak minutes via callers.

    Kept for older imports; new code should use ``calc_volume_target``.
    """
    chronic = prev_km
    return calc_volume_target(week_type, chronic, peak_km)


def build_target(
    week_type: str,
    chronic_min: float | None,
    peak_min: float,
    *,
    weeks_until: int | None = None,
    goal_peak_min: float | None = None,
) -> dict[str, Any]:
    spec = WEEK_TYPE_SPECS[week_type]
    zone_4_pct = spec["zone_4_pct"]
    zone_5_pct = spec["zone_5_pct"]
    return {
        "target_min": calc_volume_target(
            week_type,
            chronic_min,
            peak_min,
            weeks_until=weeks_until,
            goal_peak_min=goal_peak_min,
        ),
        "easy_pct": spec["easy_pct"],
        "medium_pct": spec["medium_pct"],
        "zone_4_pct": zone_4_pct,
        "zone_5_pct": zone_5_pct,
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


def _intensity_pools(target_min: int, week_type: str) -> tuple[int, int, int]:
    spec = WEEK_TYPE_SPECS.get(week_type, WEEK_TYPE_SPECS["build"])
    easy = int(round(target_min * spec["easy_pct"] / 100))
    z4 = int(round(target_min * spec["zone_4_pct"] / 100))
    z5 = target_min - easy - z4
    if z5 < 0:
        easy += z5
        z5 = 0
    return easy, z4, z5


def _day_temp(day: dict[str, Any]) -> float:
    temp = day.get("avg_temp_c")
    if temp is None:
        return 20.0
    try:
        return float(temp)
    except (TypeError, ValueError):
        return 20.0


def split_week_sessions(
    target_min: int | None,
    week_type: str,
    days: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Split weekly target minutes into dated sessions (5 train + 2 rest)."""
    if target_min is None or target_min <= 0 or not days:
        return []

    dated = [d for d in days if isinstance(d, dict) and d.get("date")]
    if len(dated) < 7:
        return []

    week = dated[:7]
    easy_pool, z4_pool, z5_pool = _intensity_pools(target_min, week_type)

    # Rest = two hottest days; training = the other five.
    by_heat = sorted(range(7), key=lambda i: (-_day_temp(week[i]), i))
    rest_idxs = set(by_heat[:2])
    train_idxs = [i for i in range(7) if i not in rest_idxs]

    sessions: list[dict[str, Any]] = []

    if week_type == "race":
        # Minimal easy touch on coolest training day.
        cool_i = min(train_idxs, key=lambda i: (_day_temp(week[i]), i))
        sessions.append(
            {
                "date": week[cool_i]["date"],
                "sport": "running",
                "session_type": "easy",
                "duration_minutes": easy_pool,
                "intensity_pool": "easy",
            }
        )
        return sessions

    quality_i: int | None = None
    if week_type not in ("recovery",) and z4_pool > 0:
        cool_enough = [
            i for i in train_idxs if _day_temp(week[i]) < HOT_TEMP_C
        ]
        candidates = cool_enough or train_idxs
        # Prefer mid-week among candidates.
        quality_i = min(
            candidates,
            key=lambda i: (abs(i - 3), _day_temp(week[i]), i),
        )
        sessions.append(
            {
                "date": week[quality_i]["date"],
                "sport": "running",
                "session_type": "threshold",
                "duration_minutes": z4_pool,
                "intensity_pool": "z4",
            }
        )

    long_frac = 0.30 if week_type == "recovery" else 0.35
    long_min = int(round(target_min * long_frac))
    long_min = min(long_min, easy_pool)
    remaining_easy = easy_pool - long_min

    # Long on last training day; avoid adjacency to quality when possible.
    long_candidates = list(reversed(train_idxs))
    if quality_i is not None:
        non_adj = [
            i
            for i in long_candidates
            if abs(i - quality_i) > 1 and i != quality_i
        ]
        if non_adj:
            long_candidates = non_adj + [
                i for i in long_candidates if i not in non_adj
            ]
    long_i = next(
        (i for i in long_candidates if quality_i is None or i != quality_i),
        train_idxs[-1],
    )
    long_type = "recovery" if week_type == "recovery" else "long"
    sessions.append(
        {
            "date": week[long_i]["date"],
            "sport": "running",
            "session_type": long_type,
            "duration_minutes": long_min,
            "intensity_pool": "easy",
        }
    )

    easy_idxs = [
        i for i in train_idxs if i != long_i and i != quality_i
    ]
    if not easy_idxs and remaining_easy > 0:
        # Degenerate: fold remaining into long.
        sessions[-1]["duration_minutes"] += remaining_easy
        remaining_easy = 0

    if easy_idxs and remaining_easy > 0:
        base = remaining_easy // len(easy_idxs)
        rem = remaining_easy - base * len(easy_idxs)
        for n, idx in enumerate(easy_idxs):
            duration = base + (rem if n == len(easy_idxs) - 1 else 0)
            if duration <= 0:
                continue
            sessions.append(
                {
                    "date": week[idx]["date"],
                    "sport": "running",
                    "session_type": "recovery" if week_type == "recovery" else "easy",
                    "duration_minutes": duration,
                    "intensity_pool": "easy",
                }
            )

    if z5_pool > 0 and easy_idxs:
        stride_day = easy_idxs[0]
        sessions.append(
            {
                "date": week[stride_day]["date"],
                "sport": "running",
                "session_type": "sprint",
                "duration_minutes": z5_pool,
                "intensity_pool": "z5",
            }
        )

    sessions.sort(key=lambda s: str(s["date"]))
    return sessions


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
    event_title: str | None = None,
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

    peak_min = max(
        (
            float(row[3] or 0)
            for row, wt in zip(stat_rows, week_types)
            if wt == "build"
        ),
        default=max((float(row[3] or 0) for row in stat_rows), default=0.0),
    )

    chronic_min, outliers = chronic_minutes_from_rows(stat_rows)
    goal_peak = goal_peak_minutes_from_title(event_title, chronic_min, peak_min)

    training_plan: list[dict[str, Any]] = []

    for i, row in enumerate(stat_rows):
        week_start = date.fromisoformat(row[0])
        week_end = date.fromisoformat(row[1])
        week_type = week_types[i]
        is_latest = i == len(stat_rows) - 1
        load = load_at_week_end(week_end)
        weeks_until = (
            weeks_until_event(week_end, event_date) if event_date else None
        )

        block = {
            "week_description": "latest_week" if is_latest else "past_week",
            "week_type": week_type,
            "actuals": actuals_from_stat_row(row, load),
            "target": build_target(
                week_type,
                chronic_min,
                peak_min,
                weeks_until=weeks_until,
                goal_peak_min=goal_peak if event_date else None,
            ),
        }
        _enrich_week_weather(
            block, week_start, week_end, daily_weather, include_days=is_latest
        )
        training_plan.append(block)

    last_end = date.fromisoformat(stat_rows[-1][1])
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
    weeks_until_upcoming = (
        weeks_until_event(plan_end, event_date) if event_date else None
    )

    upcoming_block: dict[str, Any] = {
        "week_description": "upcoming_week",
        "week_type": plan_type,
        "actuals": empty_actuals(),
        "target": build_target(
            plan_type,
            chronic_min,
            peak_min,
            weeks_until=weeks_until_upcoming,
            goal_peak_min=goal_peak if event_date else None,
        ),
        "chronic_min": round(chronic_min, 2) if chronic_min is not None else None,
        "outlier_weeks_dropped": outliers,
    }
    if daily_weather is not None:
        upcoming_block["avg_temp_c"] = average_temp(
            daily_weather, plan_start, plan_end
        )
    upcoming_block["days"] = days_in_range(daily_weather or {}, plan_start, plan_end)
    training_plan.append(upcoming_block)

    return training_plan
