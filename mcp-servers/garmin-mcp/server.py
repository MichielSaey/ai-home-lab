import os
from datetime import date, timedelta
from typing import Any, Dict, Optional

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)
from mcp.server.fastmcp import FastMCP

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))

mcp = FastMCP("garmin-mcp", host=MCP_HOST, port=MCP_PORT)

DEFAULT_GARMIN_USERNAME = os.environ.get("GARMIN_EMAIL")
DEFAULT_GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")

_CLIENT: Optional[Garmin] = None
_CLIENT_ERROR: Optional[Dict[str, Any]] = None


def _call_optional(client: Garmin, method: str, *args, **kwargs) -> Any:
    if not hasattr(client, method):
        return None
    try:
        return getattr(client, method)(*args, **kwargs)
    except Exception as exc:
        return {"error": f"{method} failed: {exc}"}


def _init_client() -> None:
    global _CLIENT
    global _CLIENT_ERROR
    if _CLIENT is not None or _CLIENT_ERROR is not None:
        return
    if not DEFAULT_GARMIN_USERNAME or not DEFAULT_GARMIN_PASSWORD:
        _CLIENT_ERROR = {
            "error": "Missing Garmin credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD."
        }
        return
    try:
        client = Garmin(email=DEFAULT_GARMIN_USERNAME, password=DEFAULT_GARMIN_PASSWORD)
        client.login()
        _CLIENT = client
    except (GarminConnectAuthenticationError, GarminConnectConnectionError) as exc:
        _CLIENT_ERROR = {"error": str(exc)}


def _get_client_or_error() -> tuple[Optional[Garmin], Optional[Dict[str, Any]]]:
    _init_client()
    if _CLIENT_ERROR is not None:
        return None, _CLIENT_ERROR
    if _CLIENT is None:
        return None, {"error": "Garmin client not initialized."}
    return _CLIENT, None


@mcp.resource("garmin://weekly-report")
def weekly_report() -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    profile = get_profile()
    weekly_mileage = get_weekly_mileage()
    events = get_events()
    race_predictions = get_race_predictions()
    activities = get_activities(days_back=14)

    return {
        "profile": profile,
        "race_predictions": race_predictions,
        "weekly_mileage": weekly_mileage,
        "activities": activities,
        "events": events,
    }


@mcp.tool()
def get_profile() -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    profile = _call_optional(client, "get_user_profile").get("userData", {})
    return {
        "weight": round(profile.get("weight", 0) / 1000, 2),  # weight (kg)
        "height": profile.get("height"),  # height (cm)
        "birthDate": profile.get("birthDate"),  # birthdate
        "vo2MaxRunning": profile.get("vo2MaxRunning"),  # VO2 max (running)
        "lactateThresholdSpeed": round(
            (profile.get("lactateThresholdSpeed", 0) * 1000 / 60), 2
        ),  # lactate threshold speed (m/s)
        "lactateThresholdHeartRate": profile.get("lactateThresholdHeartRate"),  # lactate threshold HR (bpm)
        "availableTrainingDays": profile.get("availableTrainingDays", []),  # available training days
        "preferredLongTrainingDays": profile.get(
            "preferredLongTrainingDays", []
        ),  # preferred long training days
    }


@mcp.tool()
def get_activities(days_back: int = 7) -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    activity_columns = [
        "n",
        "t",
        "d",
        "dur",
        "ap",
        "mp",
        "mxh",
        "avh",
        "ae",
        "ane",
        "tel",
    ]
    today = date.today()
    start_date = (today - timedelta(days=days_back)).isoformat()
    end_date = today.isoformat()

    activities = _call_optional(client, "get_activities_by_date", start_date, end_date)
    if isinstance(activities, dict) and activities.get("error"):
        return activities
    if not isinstance(activities, list):
        return {"error": "No activities returned from Garmin"}

    activity_rows = []
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        if activity.get("activityType", {}).get("typeKey") != "running":
            continue
        avg_speed = activity.get("averageSpeed")
        max_speed = activity.get("maxSpeed")
        row = [
            activity.get("activityName"),
            activity.get("activityType", {}).get("typeKey"),
            round((activity.get("distance", 0) or 0) / 1000, 2),
            round((activity.get("movingDuration", 0) or 0) / 60, 2),
            round((1000 / avg_speed) / 60, 2) if avg_speed else None,
            round((1000 / max_speed) / 60, 2) if max_speed else None,
            activity.get("maxHR"),
            activity.get("averageHR"),
            round(activity.get("aerobicTrainingEffect", 0) or 0, 2),
            round(activity.get("anaerobicTrainingEffect", 0) or 0, 2),
            activity.get("trainingEffectLabel"),
        ]
        activity_rows.append(row)

    return {
        "Garmin activities_past_week": {
            "Headers": activity_columns,
            "Rows": activity_rows,
        }
    }


@mcp.tool()
def get_events(months_ahead: int = 12) -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    event_columns = ["t", "it", "d", "cv", "cu", "ct"]
    today = date.today()
    start_month = today.replace(day=1)
    event_rows = []
    seen_titles = set()

    for offset in range(months_ahead):
        year = start_month.year + (start_month.month - 1 + offset) // 12
        month = (start_month.month - 1 + offset) % 12 + 1
        calendar_payload = _call_optional(
            client, "get_scheduled_workouts", year=year, month=month
        )
        if not isinstance(calendar_payload, dict):
            continue
        if calendar_payload.get("error"):
            continue
        calendar_items = calendar_payload.get("calendarItems", [])
        if not isinstance(calendar_items, list):
            continue

        for event in calendar_items:
            if not isinstance(event, dict):
                continue
            if event.get("itemType") != "event":
                continue
            event_date_str = event.get("date")
            if not event_date_str:
                continue
            try:
                event_date = date.fromisoformat(event_date_str)
            except ValueError:
                continue
            if event_date <= today:
                continue
            title = (event.get("title") or "").strip().lower()
            if title in seen_titles:
                continue
            seen_titles.add(title)

            completion_target = event.get("completionTarget") or {}
            event_rows.append(
                [
                    event.get("title"),
                    event.get("itemType"),
                    event_date_str,
                    completion_target.get("value"),
                    completion_target.get("unit"),
                    completion_target.get("unitType"),
                ]
            )

    return {
        "Garmin Events": {
            "Headers": event_columns,
            "Rows": event_rows,
        }
    }


@mcp.tool()
def get_race_predictions() -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    prediction_source = _call_optional(client, "get_race_predictions")
    if not isinstance(prediction_source, dict):
        return {"error": "No race predictions returned from Garmin"}
    if prediction_source.get("error"):
        return prediction_source

    return {
        "Garmin Race Predictions": {
            "Headers": ["5k", "10k", "hm", "m"],
            "Rows": [
                [
                    round((prediction_source.get("time5K", 0) or 0) / 60, 2),
                    round((prediction_source.get("time10K", 0) or 0) / 60, 2),
                    round(
                        (prediction_source.get("timeHalfMarathon", 0) or 0) / 3600, 2
                    ),
                    round((prediction_source.get("timeMarathon", 0) or 0) / 3600, 2),
                ]
            ],
        }
    }


@mcp.tool()
def get_weekly_mileage() -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error
    today = date.today()
    activities_28_days = _call_optional(
        client,
        "get_activities_by_date",
        (today - timedelta(days=27)).isoformat(),
        today.isoformat(),
    )
    if isinstance(activities_28_days, dict) and activities_28_days.get("error"):
        return activities_28_days
    if not isinstance(activities_28_days, list):
        return {"error": "No activities returned from Garmin"}

    weekly_rows = []
    for block_index in range(3, -1, -1):
        block_end = today - timedelta(days=block_index * 7)
        block_start = block_end - timedelta(days=6)
        block_distance_km = 0.0
        for activity in activities_28_days:
            if not isinstance(activity, dict):
                continue
            if activity.get("activityType", {}).get("typeKey") != "running":
                continue
            start_time = activity.get("startTimeLocal", "")
            if not start_time:
                continue
            try:
                activity_date = date.fromisoformat(start_time[:10])
            except ValueError:
                continue
            if block_start <= activity_date <= block_end:
                block_distance_km += (activity.get("distance", 0) or 0) / 1000

        weekly_rows.append(
            [
                block_start.isoformat(),
                block_end.isoformat(),
                round(block_distance_km, 2),
            ]
        )

    return {"Garmin Weekly Mileage": weekly_rows}


if __name__ == "__main__":
    mcp.run(transport="sse")
