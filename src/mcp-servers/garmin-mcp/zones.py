from datetime import date, timedelta
from typing import Any

# Distance for volume targets stays run-like only. HR zones roll up from every
# activity type so intensity is workout-independent / cross-training friendly.
_RUNNING_DISTANCE_TYPE_KEYS = frozenset(
    {
        "running",
        "trail_running",
        "treadmill_running",
        "track_running",
        "virtual_run",
        "indoor_running",
        "ultramarathon",
    }
)


def activity_type_key(activity: dict[str, Any]) -> str | None:
    activity_type = activity.get("activityType")
    if isinstance(activity_type, dict):
        key = activity_type.get("typeKey")
        return str(key) if key is not None else None
    if isinstance(activity_type, str) and activity_type:
        return activity_type
    return None


def counts_toward_run_distance(activity: dict[str, Any]) -> bool:
    """True when activity distance should feed running volume targets."""
    key = activity_type_key(activity)
    if key is None:
        # Legacy fixtures / bare rows without type — treat as run distance.
        return True
    return key in _RUNNING_DISTANCE_TYPE_KEYS


def normalize_hr_zones(raw: Any) -> dict[int, float]:
    zones: dict[int, float] = {}
    if not isinstance(raw, list):
        return zones
    for entry in raw:
        if not isinstance(entry, dict) or "zoneNumber" not in entry:
            continue
        zones[int(entry["zoneNumber"])] = float(entry.get("secsInZone") or 0)
    return zones


def zones_to_minute_columns(zones: dict[int, float]) -> list[float | None]:
    if not zones:
        return [None] * 5
    return [round(zones.get(zone, 0) / 60, 2) for zone in range(1, 6)]


def intensity_split_from_zones(
    zones: dict[int, float],
) -> tuple[
    float,
    float,
    float,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    """Split zone time into polarized buckets plus Z4/Z5 shares.

    Returns:
        (easy_min, medium_min, hard_min, easy_pct, medium_pct, hard_pct,
         zone_4_pct, zone_5_pct)

    Buckets: easy (Z1-2), medium (Z3 / gray zone), hard (Z4+Z5).
    Percentages are over total tracked time (Z1–Z5) and are None when empty.
    """
    easy_secs = zones.get(1, 0) + zones.get(2, 0)
    medium_secs = zones.get(3, 0)
    z4_secs = zones.get(4, 0)
    z5_secs = zones.get(5, 0)
    hard_secs = z4_secs + z5_secs
    total_secs = easy_secs + medium_secs + hard_secs
    if total_secs:
        easy_pct = round(100 * easy_secs / total_secs, 1)
        medium_pct = round(100 * medium_secs / total_secs, 1)
        hard_pct = round(100 * hard_secs / total_secs, 1)
        zone_4_pct = round(100 * z4_secs / total_secs, 1)
        zone_5_pct = round(100 * z5_secs / total_secs, 1)
    else:
        easy_pct = medium_pct = hard_pct = zone_4_pct = zone_5_pct = None
    return (
        round(easy_secs / 60, 2),
        round(medium_secs / 60, 2),
        round(hard_secs / 60, 2),
        easy_pct,
        medium_pct,
        hard_pct,
        zone_4_pct,
        zone_5_pct,
    )


def activity_date(activity: dict[str, Any]) -> date | None:
    start_time = activity.get("startTimeLocal", "")
    if not start_time:
        return None
    try:
        return date.fromisoformat(start_time[:10])
    except ValueError:
        return None


def weekly_stats_rows(
    activities: list[dict[str, Any]],
    activity_zones: dict[Any, dict[int, float]],
    anchor_end: date,
    num_blocks: int = 4,
) -> list[list[Any]]:
    """Rolling 7-day blocks ending on ``anchor_end`` (typically yesterday).

    Each block covers 7 complete days: [anchor_end - 6, anchor_end]. No partial
    calendar week that includes today.

    Row layout:
        start, end, distance_km, total_zone_min, z1..z5,
        easy_min, medium_min, hard_min,
        easy_pct, medium_pct, hard_pct, zone_4_pct, zone_5_pct
    """
    rows: list[list[Any]] = []
    for block_index in range(num_blocks - 1, -1, -1):
        block_end = anchor_end - timedelta(days=block_index * 7)
        block_start = block_end - timedelta(days=6)
        block_distance_km = 0.0
        block_zones = {zone: 0.0 for zone in range(1, 6)}
        for activity in activities:
            act_date = activity_date(activity)
            if act_date is None or not (block_start <= act_date <= block_end):
                continue
            # km volume = run-like sports only (avoid cycling km inflating targets)
            if counts_toward_run_distance(activity):
                block_distance_km += (activity.get("distance", 0) or 0) / 1000
            zones = activity_zones.get(activity.get("activityId"), {})
            for zone, secs in zones.items():
                if 1 <= zone <= 5:
                    block_zones[zone] += secs
        (
            easy_min,
            medium_min,
            hard_min,
            easy_pct,
            medium_pct,
            hard_pct,
            zone_4_pct,
            zone_5_pct,
        ) = intensity_split_from_zones(block_zones)
        zone_mins = [round(block_zones[zone] / 60, 2) for zone in range(1, 6)]
        total_zone_min = round(sum(zone_mins), 2)
        rows.append(
            [
                block_start.isoformat(),
                block_end.isoformat(),
                round(block_distance_km, 2),
                total_zone_min,
                *zone_mins,
                easy_min,
                medium_min,
                hard_min,
                easy_pct,
                medium_pct,
                hard_pct,
                zone_4_pct,
                zone_5_pct,
            ]
        )
    return rows


def weekly_hr_zone_rows(
    dated_zones: list[tuple[date, dict[int, float]]],
    anchor_end: date,
    num_blocks: int = 4,
) -> list[list[Any]]:
    """Time-only HR zone rollup (no distance) for cross-training overviews.

    Row layout:
        start, end, total_zone_min, z1..z5,
        easy_min, medium_min, hard_min,
        easy_pct, medium_pct, hard_pct, zone_4_pct, zone_5_pct
    """
    rows: list[list[Any]] = []
    for block_index in range(num_blocks - 1, -1, -1):
        block_end = anchor_end - timedelta(days=block_index * 7)
        block_start = block_end - timedelta(days=6)
        block_zones = {zone: 0.0 for zone in range(1, 6)}
        for act_date, zones in dated_zones:
            if block_start <= act_date <= block_end:
                for zone, secs in zones.items():
                    if 1 <= zone <= 5:
                        block_zones[zone] += secs
        (
            easy_min,
            medium_min,
            hard_min,
            easy_pct,
            medium_pct,
            hard_pct,
            zone_4_pct,
            zone_5_pct,
        ) = intensity_split_from_zones(block_zones)
        zone_mins = [round(block_zones[zone] / 60, 2) for zone in range(1, 6)]
        total_zone_min = round(sum(zone_mins), 2)
        rows.append(
            [
                block_start.isoformat(),
                block_end.isoformat(),
                total_zone_min,
                *zone_mins,
                easy_min,
                medium_min,
                hard_min,
                easy_pct,
                medium_pct,
                hard_pct,
                zone_4_pct,
                zone_5_pct,
            ]
        )
    return rows
