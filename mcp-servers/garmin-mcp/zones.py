from datetime import date, timedelta
from typing import Any


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


def easy_hard_from_zones(
    zones: dict[int, float],
) -> tuple[float, float, float | None]:
    easy_secs = zones.get(1, 0) + zones.get(2, 0)
    hard_secs = zones.get(3, 0) + zones.get(4, 0) + zones.get(5, 0)
    total_secs = easy_secs + hard_secs
    easy_pct = round(100 * easy_secs / total_secs, 1) if total_secs else None
    return round(easy_secs / 60, 2), round(hard_secs / 60, 2), easy_pct


def activity_date(activity: dict[str, Any]) -> date | None:
    start_time = activity.get("startTimeLocal", "")
    if not start_time:
        return None
    try:
        return date.fromisoformat(start_time[:10])
    except ValueError:
        return None


def weekly_hr_zone_rows(
    dated_zones: list[tuple[date, dict[int, float]]],
    today: date,
    num_blocks: int = 4,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for block_index in range(num_blocks - 1, -1, -1):
        block_end = today - timedelta(days=block_index * 7)
        block_start = block_end - timedelta(days=6)
        block_zones = {zone: 0.0 for zone in range(1, 6)}
        for act_date, zones in dated_zones:
            if block_start <= act_date <= block_end:
                for zone, secs in zones.items():
                    if 1 <= zone <= 5:
                        block_zones[zone] += secs
        easy_min, hard_min, easy_pct = easy_hard_from_zones(block_zones)
        rows.append(
            [
                block_start.isoformat(),
                block_end.isoformat(),
                *[round(block_zones[zone] / 60, 2) for zone in range(1, 6)],
                easy_min,
                hard_min,
                easy_pct,
            ]
        )
    return rows
