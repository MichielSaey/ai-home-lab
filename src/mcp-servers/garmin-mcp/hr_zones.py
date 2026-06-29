"""Heart rate zone helpers for Garmin running workouts.

Zones follow the Karvonen (heart rate reserve) method used by McMillan/WHOOP:
- Zone 1: 55-65% HRR — recovery
- Zone 2: 55-78% HRR — easy and long runs
- Zone 3: 75-80% HRR — steady state / tempo
- Zone 4: 80-85% HRR — lactate threshold
- Zone 5: 90-100% HRR — strides, sprints, VO2max
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

from garminconnect import Garmin
from garminconnect.workout import TargetType

# Garmin workout templates map to these zone numbers (1-5).
# Polarized model: prescribe only low (Z1-2) and high (Z4-5); never Z3.
WORKOUT_ZONE_TARGETS: Dict[str, int] = {
    "recovery": 1,
    "base": 2,
    "long_run": 2,
    "weighted_pack": 2,
    "threshold": 4,
    "sprint": 5,
    "hill_repeats": 5,
    "interval_recovery": 1,
    "warmup": 2,
    "cooldown": 1,
}

ZONE_DEFINITIONS = (
    (1, 0.55, 0.65, "Recovery"),
    (2, 0.55, 0.78, "Easy / long run"),
    (3, 0.75, 0.80, "Steady state / tempo"),
    (4, 0.80, 0.85, "Lactate threshold"),
    (5, 0.90, 1.00, "Speed / VO2max / sprints"),
)


@dataclass(frozen=True)
class HeartRateZone:
    zone: int
    label: str
    min_bpm: int
    max_bpm: int


def _estimate_age(birth_date: Optional[str]) -> Optional[int]:
    if not birth_date:
        return None
    try:
        born = date.fromisoformat(birth_date[:10])
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _estimate_max_hr(profile: Dict[str, Any], age: Optional[int]) -> int:
    if age is not None:
        return max(120, 220 - age)
    lthr = profile.get("lactateThresholdHeartRate")
    if isinstance(lthr, int) and lthr > 0:
        return int(lthr / 0.85)
    return 185


def _fetch_resting_hr(client: Garmin) -> Optional[int]:
    if not hasattr(client, "get_heart_rates"):
        return None
    try:
        payload = client.get_heart_rates(date.today().isoformat())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    resting = payload.get("restingHeartRate")
    return int(resting) if isinstance(resting, int) and resting > 0 else None


def build_zone_table(max_hr: int, resting_hr: int) -> Dict[int, HeartRateZone]:
    hrr = max(max_hr - resting_hr, 1)
    zones: Dict[int, HeartRateZone] = {}
    for zone, low_pct, high_pct, label in ZONE_DEFINITIONS:
        zones[zone] = HeartRateZone(
            zone=zone,
            label=label,
            min_bpm=round(hrr * low_pct + resting_hr),
            max_bpm=round(hrr * high_pct + resting_hr),
        )
    return zones


def resolve_hr_context(client: Garmin, profile: Dict[str, Any]) -> Dict[str, Any]:
    user_data = {}
    if hasattr(client, "get_user_profile"):
        try:
            raw = client.get_user_profile()
            if isinstance(raw, dict):
                user_data = raw.get("userData", {}) or {}
        except Exception:
            user_data = {}

    age = _estimate_age(user_data.get("birthDate") or profile.get("birthDate"))
    resting_hr = _fetch_resting_hr(client) or 55
    max_hr = _estimate_max_hr(profile, age)
    lthr = profile.get("lactateThresholdHeartRate")

    zones = build_zone_table(max_hr, resting_hr)
    return {
        "restingHeartRate": resting_hr,
        "estimatedMaxHeartRate": max_hr,
        "lactateThresholdHeartRate": lthr,
        "zones": {
            str(zone): {
                "label": info.label,
                "minBpm": info.min_bpm,
                "maxBpm": info.max_bpm,
                "garminZoneNumber": zone,
            }
            for zone, info in zones.items()
        },
        "workoutZoneMap": WORKOUT_ZONE_TARGETS,
    }


def heart_rate_zone_target() -> Dict[str, Any]:
    return {
        "workoutTargetTypeId": TargetType.HEART_RATE_ZONE,
        "workoutTargetTypeKey": "heart.rate.zone",
        "displayOrder": 4,
    }


def zone_for_workout_type(workout_type: str) -> int:
    return WORKOUT_ZONE_TARGETS.get(workout_type, 2)
