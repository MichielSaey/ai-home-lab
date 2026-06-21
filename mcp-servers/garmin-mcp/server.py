import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)
from mcp.server.fastmcp import FastMCP

from errors import (
    AUTH_FAILED,
    CONNECTION_ERROR,
    MISSING_CREDENTIALS,
    NOT_INITIALIZED,
    UNKNOWN,
    structured_error,
)
from rest_shim import mount_rest_routes
from training_plan import build_training_plan, first_event_date
from training_status import parse_training_status
from zones import (
    activity_date,
    normalize_hr_zones,
    weekly_stats_rows,
    zones_to_minute_columns,
)

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))

mcp = FastMCP("garmin-mcp", host=MCP_HOST, port=MCP_PORT)

DEFAULT_GARMIN_USERNAME = os.environ.get("GARMIN_EMAIL")
DEFAULT_GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")

_CLIENT: Optional[Garmin] = None
_CLIENT_ERROR: Optional[Dict[str, Any]] = None

ACTIVITY_HEADERS = [
    "name",
    "type",
    "distance_km",
    "duration_min",
    "avg_pace_min_per_km",
    "max_pace_min_per_km",
    "max_hr",
    "avg_hr",
    "aerobic_te",
    "anaerobic_te",
    "training_effect",
    "zone_1_min",
    "zone_2_min",
    "zone_3_min",
    "zone_4_min",
    "zone_5_min",
]

ACTIVITY_HEADERS_NO_ZONES = ACTIVITY_HEADERS[:11]

WEEKLY_STATS_HEADERS = [
    "week_start",
    "week_end",
    "distance_km",
    "zone_1_min",
    "zone_2_min",
    "zone_3_min",
    "zone_4_min",
    "zone_5_min",
    "easy_min",
    "hard_min",
    "easy_pct",
]


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
        _CLIENT_ERROR = structured_error(
            MISSING_CREDENTIALS,
            "Missing Garmin credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD.",
            retryable=False,
        )
        return
    try:
        client = Garmin(email=DEFAULT_GARMIN_USERNAME, password=DEFAULT_GARMIN_PASSWORD)
        client.login()
        _CLIENT = client
    except GarminConnectAuthenticationError as exc:
        _CLIENT_ERROR = structured_error(
            AUTH_FAILED,
            str(exc),
            retryable=False,
        )
    except GarminConnectConnectionError as exc:
        _CLIENT_ERROR = structured_error(
            CONNECTION_ERROR,
            str(exc),
            retryable=True,
        )
    except Exception as exc:
        _CLIENT_ERROR = structured_error(
            UNKNOWN,
            str(exc),
            retryable=True,
        )


def _get_client_or_error() -> tuple[Optional[Garmin], Optional[Dict[str, Any]]]:
    _init_client()
    if _CLIENT_ERROR is not None:
        return None, _CLIENT_ERROR
    if _CLIENT is None:
        return None, structured_error(
            NOT_INITIALIZED,
            "Garmin client not initialized.",
            retryable=True,
        )
    return _CLIENT, None


def _health_checked_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _garmin_health_payload() -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error is not None:
        return {
            "status": "error",
            "garmin": error,
            "checkedAt": _health_checked_at(),
        }

    probe = _call_optional(client, "get_user_profile")
    if isinstance(probe, dict) and probe.get("error"):
        return {
            "status": "error",
            "garmin": structured_error(
                CONNECTION_ERROR,
                str(probe["error"]),
                retryable=True,
            ),
            "checkedAt": _health_checked_at(),
        }

    return {
        "status": "ok",
        "garmin": {
            "reachable": True,
            "authenticated": True,
        },
        "checkedAt": _health_checked_at(),
    }


def _fetch_hr_zones(client: Garmin, activity_id: Any) -> dict[int, float]:
    raw = _call_optional(client, "get_activity_hr_in_timezones", str(activity_id))
    if isinstance(raw, dict) and raw.get("error"):
        return {}
    return normalize_hr_zones(raw)


def _running_activities_in_range(
    client: Garmin, start_date: str, end_date: str
) -> list[dict[str, Any]] | dict[str, Any]:
    activities = _call_optional(client, "get_activities_by_date", start_date, end_date)
    if isinstance(activities, dict) and activities.get("error"):
        return activities
    if not isinstance(activities, list):
        return {"error": "No activities returned from Garmin"}
    return [
        activity
        for activity in activities
        if isinstance(activity, dict)
        and activity.get("activityType", {}).get("typeKey") == "running"
    ]


def _activity_row(
    activity: dict[str, Any],
    zones: dict[int, float],
    *,
    include_hr_zones: bool,
) -> list[Any]:
    avg_speed = activity.get("averageSpeed")
    max_speed = activity.get("maxSpeed")
    row: list[Any] = [
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
    if include_hr_zones:
        row.extend(zones_to_minute_columns(zones))
    return row


def _activities_table(
    client: Garmin,
    days_back: int,
    *,
    include_hr_zones: bool = True,
) -> Dict[str, Any] | dict[str, Any]:
    today = date.today()
    activities = _running_activities_in_range(
        client,
        (today - timedelta(days=days_back)).isoformat(),
        today.isoformat(),
    )
    if isinstance(activities, dict) and activities.get("error"):
        return activities

    headers = ACTIVITY_HEADERS if include_hr_zones else ACTIVITY_HEADERS_NO_ZONES
    rows = []
    for activity in activities:
        zones = (
            _fetch_hr_zones(client, activity.get("activityId"))
            if include_hr_zones
            else {}
        )
        rows.append(_activity_row(activity, zones, include_hr_zones=include_hr_zones))

    return {
        "Garmin Activities": {
            "Headers": headers,
            "Rows": rows,
        }
    }


def _weekly_stats_table(client: Garmin, weeks: int = 4) -> Dict[str, Any] | dict[str, Any]:
    today = date.today()
    lookback_days = weeks * 7 - 1
    activities = _running_activities_in_range(
        client,
        (today - timedelta(days=lookback_days)).isoformat(),
        today.isoformat(),
    )
    if isinstance(activities, dict) and activities.get("error"):
        return activities

    activity_zones: dict[Any, dict[int, float]] = {}
    for activity in activities:
        activity_id = activity.get("activityId")
        if activity_id is None:
            continue
        activity_zones[activity_id] = _fetch_hr_zones(client, activity_id)

    return {
        "Garmin Weekly Stats": {
            "Headers": WEEKLY_STATS_HEADERS,
            "Rows": weekly_stats_rows(activities, activity_zones, today, num_blocks=weeks),
        }
    }


def _training_plan_table(
    client: Garmin, events: Dict[str, Any], weeks: int = 4
) -> list[dict[str, Any]] | dict[str, Any]:
    stats = _weekly_stats_table(client, weeks=weeks)
    if isinstance(stats, dict) and stats.get("error"):
        return stats

    event_rows = events.get("Garmin Events", {}).get("Rows", [])
    event_date = first_event_date(event_rows)
    stat_rows = stats["Garmin Weekly Stats"]["Rows"]

    def load_at_week_end(week_end: date) -> dict[str, Any]:
        raw = _call_optional(client, "get_training_status", week_end.isoformat())
        if isinstance(raw, dict) and raw.get("error"):
            return {}
        return parse_training_status(raw if isinstance(raw, dict) else {})

    return build_training_plan(stat_rows, event_date, load_at_week_end)


@mcp.tool()
def get_profile() -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    raw = _call_optional(client, "get_user_profile")
    if isinstance(raw, dict) and raw.get("error"):
        return raw
    profile = (raw or {}).get("userData", {})
    return {
        "weight": round(profile.get("weight", 0) / 1000, 2),
        "height": profile.get("height"),
        "birthDate": profile.get("birthDate"),
        "vo2MaxRunning": profile.get("vo2MaxRunning"),
        "lactateThresholdSpeed": round(
            (profile.get("lactateThresholdSpeed", 0) * 1000 / 60), 2
        ),
        "lactateThresholdHeartRate": profile.get("lactateThresholdHeartRate"),
        "availableTrainingDays": profile.get("availableTrainingDays", []),
        "preferredLongTrainingDays": profile.get(
            "preferredLongTrainingDays", []
        ),
    }


@mcp.tool()
def get_activities(days_back: int = 7, include_hr_zones: bool = True) -> Dict[str, Any]:
    """Running activities in the last N days. Set include_hr_zones=false for a faster summary."""
    client, error = _get_client_or_error()
    if error:
        return error
    return _activities_table(client, days_back, include_hr_zones=include_hr_zones)


@mcp.tool()
def get_weekly_stats(weeks: int = 4) -> Dict[str, Any]:
    """Weekly running distance and HR zone rollups (one row per calendar week)."""
    client, error = _get_client_or_error()
    if error:
        return error
    return _weekly_stats_table(client, weeks=weeks)


@mcp.tool()
def get_training_plan(weeks: int = 4) -> list[dict[str, Any]] | Dict[str, Any]:
    """Periodized plan: 4 past weeks + upcoming week with actuals, targets, and load."""
    client, error = _get_client_or_error()
    if error:
        return error

    events = get_events()
    if isinstance(events, dict) and events.get("error"):
        return events

    return _training_plan_table(client, events, weeks=weeks)


@mcp.tool()
def get_weekly_report(days_back: int = 7, include_activities: bool = False) -> Dict[str, Any]:
    """Coach review bundle: profile, predictions, events, and training plan. Slow — call on demand."""
    client, error = _get_client_or_error()
    if error:
        return error

    events = get_events()
    if isinstance(events, dict) and events.get("error"):
        return events

    training_plan = _training_plan_table(client, events)
    if isinstance(training_plan, dict) and training_plan.get("error"):
        return training_plan

    report: Dict[str, Any] = {
        "profile": get_profile(),
        "race_predictions": get_race_predictions(),
        "events": events,
        "training_plan": training_plan,
    }
    if include_activities:
        report["activities"] = _activities_table(
            client, days_back, include_hr_zones=True
        )
    return report


@mcp.resource("garmin://health")
def health() -> Dict[str, Any]:
    """Lightweight Garmin Connect reachability check (no weekly report)."""
    return _garmin_health_payload()


@mcp.resource("garmin://weekly-report")
def weekly_report() -> Dict[str, Any]:
    """Default weekly review bundle (last 7 days). Alias for get_weekly_report."""
    return get_weekly_report()


@mcp.resource("garmin://weekly-report/{days_back}")
def weekly_report_for_days(days_back: int) -> Dict[str, Any]:
    """Review bundle for a custom look-back window (days_back)."""
    days_back = max(1, min(days_back, 90))
    return get_weekly_report(days_back=days_back)


@mcp.tool()
def get_events(months_ahead: int = 12) -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    event_columns = [
        "title",
        "item_type",
        "date",
        "target_value",
        "target_unit",
        "target_unit_type",
    ]
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
            "Headers": ["5k_min", "10k_min", "half_marathon_h", "marathon_h"],
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


# TODO: Excersies creation and scheduling tool
# Start with minimalist funciton that takes a json for the workout.
# From there add tools for pre-defined workout types (e.g., Quality, Threshold, Tempo, Endurance, etc.)
# These tools should have minimal inputs. A set of paramaters defining repetition, and duration. But as
# much as possible should be done automatically. Then there should be a schedule tool, that takes an
# workout id, and a date, and schedules the workout for that date. Or we could add date as a pramater
# in the create tool.

mount_rest_routes(mcp)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "sse")
    mcp.run(transport=transport)  # type: ignore[arg-type]
