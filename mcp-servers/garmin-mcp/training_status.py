from typing import Any


def _primary_device_entry(device_map: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(device_map, dict):
        return {}
    for entry in device_map.values():
        if isinstance(entry, dict) and entry.get("primaryTrainingDevice"):
            return entry
    for entry in device_map.values():
        if isinstance(entry, dict):
            return entry
    return {}


def parse_training_status(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    status = _primary_device_entry(
        (raw.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
    )
    load = status.get("acuteTrainingLoadDTO") or {}
    return {
        "acute_load": load.get("dailyTrainingLoadAcute"),
        "chronic_load": load.get("dailyTrainingLoadChronic"),
        "acwr": load.get("dailyAcuteChronicWorkloadRatio"),
        "training_status": status.get("trainingStatusFeedbackPhrase"),
    }
