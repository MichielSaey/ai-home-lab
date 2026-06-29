from datetime import date, timedelta
from typing import Any, Callable

# Polarized targets: medium (Zone 3) should always be ~0 — it is the gray zone
# to minimize. easy_pct + hard_pct therefore sum to 100 for every week type.
WEEK_TYPE_SPECS = {
    "build": {"multiplier": 1.10, "easy_pct": 80, "medium_pct": 0, "hard_pct": 20, "ref": "prev"},
    "recovery": {"multiplier": 0.80, "easy_pct": 90, "medium_pct": 0, "hard_pct": 10, "ref": "prev"},
    "taper_first": {"multiplier": 0.80, "easy_pct": 80, "medium_pct": 0, "hard_pct": 20, "ref": "peak"},
    "taper_final": {"multiplier": 0.64, "easy_pct": 85, "medium_pct": 0, "hard_pct": 15, "ref": "peak"},
    "race": {"multiplier": 0.30, "easy_pct": 90, "medium_pct": 0, "hard_pct": 10, "ref": "prev"},
}


def weeks_until_event(from_date: date, event_date: date) -> int:
    return max(0, (event_date - from_date).days // 7)


def classify_week_type(week_number: int, weeks_until: int | None) -> str:
    if weeks_until is not None:
        if weeks_until == 0:
            return "race"
        if weeks_until == 1:
            return "taper_final"
        if weeks_until == 2:
            return "taper_first"
    if week_number % 4 == 0:
        return "recovery"
    return "build"


def first_event_date(event_rows: list[list[Any]], today: date | None = None) -> date | None:
    today = today or date.today()
    upcoming: list[date] = []
    for row in event_rows:
        try:
            event_date = date.fromisoformat(row[2])
        except (ValueError, IndexError):
            continue
        if event_date > today:
            upcoming.append(event_date)
    return min(upcoming) if upcoming else None


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
    return {
        "distance_km": calc_distance_target(week_type, prev_km, peak_km),
        "easy_pct": spec["easy_pct"],
        "medium_pct": spec["medium_pct"],
        "hard_pct": spec["hard_pct"],
    }


def calc_acwr(acute: Any, chronic: Any) -> float | None:
    if acute is None or chronic is None or chronic == 0:
        return None
    return round(float(acute) / float(chronic), 2)


def actuals_from_stat_row(row: list[Any], load: dict[str, Any]) -> dict[str, Any]:
    # Row layout (weekly_stats_rows): start, end, distance, z1..z5,
    # easy_min, medium_min, hard_min, easy_pct, medium_pct, hard_pct
    easy_pct = row[11]
    medium_pct = row[12]
    hard_pct = row[13]
    acute = load.get("acute_load")
    chronic = load.get("chronic_load")
    return {
        "distance_km": row[2],
        "easy_pct": easy_pct,
        "medium_pct": medium_pct,
        "hard_pct": hard_pct,
        "acute_load": acute,
        "chronic_load": chronic,
        "acwr": calc_acwr(acute, chronic),
    }


def empty_actuals() -> dict[str, Any]:
    return {
        "distance_km": None,
        "easy_pct": None,
        "medium_pct": None,
        "hard_pct": None,
        "acute_load": None,
        "chronic_load": None,
        "acwr": None,
    }


def build_training_plan(
    stat_rows: list[list[Any]],
    event_date: date | None,
    load_at_week_end: Callable[[date], dict[str, Any]],
) -> list[dict[str, Any]]:
    if not stat_rows:
        return []

    week_types: list[str] = []
    for i, row in enumerate(stat_rows):
        week_end = date.fromisoformat(row[1])
        w_until = weeks_until_event(week_end, event_date) if event_date else None
        week_types.append(classify_week_type(i + 1, w_until))

    peak_km = max(
        (float(row[2] or 0) for row, wt in zip(stat_rows, week_types) if wt == "build"),
        default=max((float(row[2] or 0) for row in stat_rows), default=0),
    )

    training_plan: list[dict[str, Any]] = []
    prev_km: float | None = None

    for i, row in enumerate(stat_rows):
        week_end = date.fromisoformat(row[1])
        week_type = week_types[i]
        is_current = i == len(stat_rows) - 1
        load = load_at_week_end(week_end)

        training_plan.append(
            {
                "week_description": "current_week" if is_current else "past_week",
                "week_type": week_type,
                "actuals": actuals_from_stat_row(row, load),
                "target": build_target(week_type, prev_km, peak_km),
            }
        )
        prev_km = float(row[2] or 0) or prev_km

    last_end = date.fromisoformat(stat_rows[-1][1])
    plan_start = last_end + timedelta(days=1)
    while plan_start.weekday() != 0:
        plan_start += timedelta(days=1)
    plan_week_num = len(stat_rows) + 1
    plan_w_until = weeks_until_event(plan_start, event_date) if event_date else None
    plan_type = classify_week_type(plan_week_num, plan_w_until)

    training_plan.append(
        {
            "week_description": "upcoming_week",
            "week_type": plan_type,
            "actuals": empty_actuals(),
            "target": build_target(plan_type, prev_km, peak_km),
        }
    )

    return training_plan
