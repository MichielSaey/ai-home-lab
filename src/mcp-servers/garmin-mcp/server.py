import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)
from mcp.server.fastmcp import FastMCP

from coaching_brief import build_coaching_brief
from errors import (
    AUTH_FAILED,
    CONNECTION_ERROR,
    MISSING_CREDENTIALS,
    NOT_INITIALIZED,
    UNKNOWN,
    structured_error,
)
from hr_zones import resolve_hr_context
from nutrition_matrix import (
    get_nutrition_cues as lookup_nutrition_cues,
    intensity_for_template,
)
from rest_shim import mount_rest_routes
from rolling_week import (
    anchor_end as compute_anchor_end,
    block_bounds,
    window_bounds,
)
from self_evaluation import extract_self_evaluation
from training_plan import (
    build_training_plan,
    first_event_date,
    first_event_title,
    last_event_date_from_payload,
    latest_event_within_days,
)
from training_status import parse_training_status
from weather import fetch_daily_weather
from zones import (
    activity_date,
    activity_type_key,
    normalize_hr_zones,
    weekly_stats_rows,
    zones_to_minute_columns,
)
from workout_builder import extract_workout_id
from workout_templates import (
    TEMPLATE_DESCRIPTIONS,
    TEMPLATE_TYPES,
    build_combined_workout,
    build_template_workout,
    estimate_combined_duration_minutes,
    estimate_template_duration_minutes,
)

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))

mcp = FastMCP("garmin-mcp", host=MCP_HOST, port=MCP_PORT)

DEFAULT_GARMIN_USERNAME = os.environ.get("GARMIN_EMAIL")
DEFAULT_GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")


def _env_float(name: str) -> Optional[float]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# Optional home location for weather lookups. When unset, weather is omitted.
GARMIN_HOME_LAT = _env_float("GARMIN_HOME_LAT")
GARMIN_HOME_LON = _env_float("GARMIN_HOME_LON")

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

# Matches weekly_stats_rows layout (see zones.py):
# start, end, distance_km, total_zone_min, z1..z5, easy/medium/hard min+pct, z4/z5 pct
WEEKLY_STATS_HEADERS = [
    "week_start",
    "week_end",
    "distance_km",
    "total_zone_min",
    "zone_1_min",
    "zone_2_min",
    "zone_3_min",
    "zone_4_min",
    "zone_5_min",
    "easy_min",
    "medium_min",
    "hard_min",
    "easy_pct",
    "medium_pct",
    "hard_pct",
    "zone_4_pct",
    "zone_5_pct",
]


def _call_optional(client: Garmin, method: str, *args, **kwargs) -> Any:
    if not hasattr(client, method):
        return None
    try:
        return getattr(client, method)(*args, **kwargs)
    except Exception as exc:
        return {"error": f"{method} failed: {exc}"}


def _calendar_item_date(item: Dict[str, Any]) -> Optional[str]:
    for key in ("date", "calendarDate"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value[:10]
    return None


def _calendar_item_workout_id(item: Dict[str, Any]) -> Optional[int]:
    for key in ("workoutId", "workoutTemplateId"):
        value = item.get(key)
        if value is not None:
            return int(value)
    workout = item.get("workout")
    if isinstance(workout, dict) and workout.get("workoutId") is not None:
        return int(workout["workoutId"])
    return None


def _find_scheduled_workout(
    client: Garmin, workout_id: int, workout_date: str
) -> Optional[Dict[str, Any]]:
    if not hasattr(client, "get_scheduled_workouts"):
        return None
    try:
        target = date.fromisoformat(workout_date)
    except ValueError:
        return None

    payload = _call_optional(
        client, "get_scheduled_workouts", year=target.year, month=target.month
    )
    if not isinstance(payload, dict) or payload.get("error"):
        return None

    items = payload.get("calendarItems", [])
    if not isinstance(items, list):
        return None

    for item in items:
        if not isinstance(item, dict):
            continue
        if _calendar_item_date(item) != workout_date:
            continue
        if _calendar_item_workout_id(item) == workout_id:
            return item
    return None


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


def _report_window(days: int, days_ago: int = 0) -> tuple[date, date]:
    return window_bounds(days, days_ago)


def _fetch_hr_zones(client: Garmin, activity_id: Any) -> dict[int, float]:
    raw = _call_optional(client, "get_activity_hr_in_timezones", str(activity_id))
    if isinstance(raw, dict) and raw.get("error"):
        return {}
    return normalize_hr_zones(raw)


def _activities_in_range(
    client: Garmin, start_date: str, end_date: str
) -> list[dict[str, Any]] | dict[str, Any]:
    """Return all dict activities in the date range (any activity type)."""
    activities = _call_optional(client, "get_activities_by_date", start_date, end_date)
    if isinstance(activities, dict) and activities.get("error"):
        return activities
    if not isinstance(activities, list):
        return {"error": "No activities returned from Garmin"}
    return [activity for activity in activities if isinstance(activity, dict)]


def _running_activities_in_range(
    client: Garmin, start_date: str, end_date: str
) -> list[dict[str, Any]] | dict[str, Any]:
    """Backward-compatible alias for ``_activities_in_range``."""
    return _activities_in_range(client, start_date, end_date)


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
        activity_type_key(activity),
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
    days_back: int = 7,
    *,
    days: Optional[int] = None,
    days_ago: int = 0,
    include_hr_zones: bool = True,
) -> Dict[str, Any] | dict[str, Any]:
    effective_days = days if days is not None else days_back
    window_start, window_end = window_bounds(effective_days, days_ago)
    start_date = window_start.isoformat()
    end_date = window_end.isoformat()

    activities = _activities_in_range(client, start_date, end_date)
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
        },
        "window": {
            "start_date": start_date,
            "end_date": end_date,
            "days": effective_days,
            "days_ago": days_ago,
        },
    }


def _recent_activity_summaries(
    activities: list[dict[str, Any]],
    *,
    limit: int = 10,
    window_start: date | None = None,
    window_end: date | None = None,
    window_limit: int = 40,
) -> list[dict[str, Any]]:
    """Lightweight recent activities for the coach.

    When ``window_start`` / ``window_end`` are set, include every activity in
    that review window (this week), not just the global last ``limit`` rows.
    """
    summaries: list[dict[str, Any]] = []
    cap = window_limit if window_start is not None and window_end is not None else limit
    for activity in sorted(
        activities, key=lambda row: row.get("startTimeLocal", ""), reverse=True
    ):
        act_date = activity_date(activity)
        if act_date is None:
            continue
        if window_start is not None and act_date < window_start:
            continue
        if window_end is not None and act_date > window_end:
            continue
        summaries.append(
            {
                "date": act_date.isoformat(),
                "activity_id": activity.get("activityId"),
                "name": activity.get("activityName"),
                "activity_type": activity_type_key(activity),
                "distance_km": round((activity.get("distance", 0) or 0) / 1000, 2),
                "duration_min": round((activity.get("movingDuration", 0) or 0) / 60, 1),
                "training_effect": activity.get("trainingEffectLabel"),
                "avg_hr": activity.get("averageHR"),
            }
        )
        if len(summaries) >= cap:
            break
    return summaries


def _enrich_self_evaluations(
    client: Garmin,
    summaries: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    window_start: date,
    window_end: date,
) -> list[dict[str, Any]]:
    """Attach Garmin self-evaluation to this-week activity summaries only.

    Extra ``get_activity`` calls cover the review window (and today when the
    window includes it). Older lookback weeks keep distance/circumstances
    without the written note or feel / RPE scores.
    """
    list_by_id: dict[str, dict[str, Any]] = {}
    for activity in activities:
        activity_id = activity.get("activityId")
        if activity_id is not None:
            list_by_id[str(activity_id)] = activity

    for summary in summaries:
        raw_date = summary.get("date")
        try:
            act_date = date.fromisoformat(str(raw_date))
        except (TypeError, ValueError):
            continue
        if act_date < window_start or act_date > window_end:
            continue
        activity_id = summary.get("activity_id")
        list_row = (
            list_by_id.get(str(activity_id)) if activity_id is not None else None
        )
        detail: dict[str, Any] | None = None
        if activity_id is not None:
            raw = _call_optional(client, "get_activity", str(activity_id))
            if isinstance(raw, dict) and not raw.get("error"):
                detail = raw
        extracted = extract_self_evaluation(list_row, detail)
        # ``self_evaluation`` is the written note (free text). Feel / RPE stay
        # as extra scores and are not a substitute for that note.
        summary["self_evaluation"] = extracted["self_evaluation"]
        summary["feeling"] = extracted["feeling"]
        summary["perceived_effort"] = extracted["perceived_effort"]
    return summaries


def _weekly_stats_table(
    client: Garmin, weeks: int = 4, *, anchor_end: Optional[date] = None
) -> Dict[str, Any] | dict[str, Any]:
    anchor = anchor_end if anchor_end is not None else compute_anchor_end()
    lookback_days = weeks * 7
    activities = _activities_in_range(
        client,
        (anchor - timedelta(days=lookback_days - 1)).isoformat(),
        date.today().isoformat(),
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
            "Rows": weekly_stats_rows(activities, activity_zones, anchor, num_blocks=weeks),
        },
        "_activities": activities,
    }


def _training_plan_table(
    client: Garmin,
    events: Dict[str, Any],
    weeks: int = 4,
    *,
    anchor_end: Optional[date] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | dict[str, Any]:
    stats = _weekly_stats_table(client, weeks=weeks, anchor_end=anchor_end)
    if isinstance(stats, dict) and stats.get("error"):
        return stats

    activities = stats.pop("_activities", [])
    event_rows = events.get("Garmin Events", {}).get("Rows", [])
    upcoming_event_date = first_event_date(event_rows)
    upcoming_event_title = first_event_title(event_rows)
    last_event_date = last_event_date_from_payload(events)
    stat_rows = stats["Garmin Weekly Stats"]["Rows"]

    def load_at_week_end(week_end: date) -> dict[str, Any]:
        raw = _call_optional(client, "get_training_status", week_end.isoformat())
        if isinstance(raw, dict) and raw.get("error"):
            return {}
        return parse_training_status(raw if isinstance(raw, dict) else {})

    daily_weather = _weather_for_plan(stat_rows)

    return (
        build_training_plan(
            stat_rows,
            upcoming_event_date,
            load_at_week_end,
            daily_weather,
            last_event_date=last_event_date,
            event_title=upcoming_event_title,
        ),
        activities,
    )


def _weather_for_plan(
    stat_rows: list[list[Any]],
) -> Optional[dict[str, dict[str, Any]]]:
    """Fetch daily weather spanning the lookback weeks plus the upcoming week.

    Returns None when no home location is configured, so the plan omits weather.
    """
    if GARMIN_HOME_LAT is None or GARMIN_HOME_LON is None or not stat_rows:
        return None

    window_start = stat_rows[0][0]
    # End covers the forecast upcoming week (last week end + up to ~13 days).
    last_end = date.fromisoformat(stat_rows[-1][1])
    window_end = (last_end + timedelta(days=14)).isoformat()

    return fetch_daily_weather(
        GARMIN_HOME_LAT, GARMIN_HOME_LON, window_start, window_end
    )


@mcp.tool()
def get_profile() -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    raw = _call_optional(client, "get_user_profile")
    if not isinstance(raw, dict):
        return {"error": "No profile returned from Garmin"}
    if raw.get("error"):
        return raw
    profile = raw.get("userData") or {}
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
def get_activities(
    days_back: int = 7,
    include_hr_zones: bool = True,
    days: Optional[int] = None,
    days_ago: int = 0,
) -> Dict[str, Any]:
    """Activities of all types in a date window. Use days/days_ago for rollable windows."""
    client, error = _get_client_or_error()
    if error:
        return error
    return _activities_table(
        client,
        days_back,
        days=days,
        days_ago=days_ago,
        include_hr_zones=include_hr_zones,
    )


@mcp.tool()
def get_weekly_stats(weeks: int = 4, end_date: Optional[str] = None) -> Dict[str, Any]:
    """Weekly distance and HR zone rollups across all activity types (rolling 7-day blocks).

    ``end_date``, when provided, is the anchor end of the latest complete block
    (typically yesterday), not a fetch-through date. Includes ``total_zone_min``
    for a time-based intensity overview.
    """
    client, error = _get_client_or_error()
    if error:
        return error
    anchor: Optional[date] = None
    if end_date is not None:
        try:
            anchor = date.fromisoformat(end_date)
        except ValueError:
            return {"error": "end_date must be an ISO date (YYYY-MM-DD)"}
    result = _weekly_stats_table(client, weeks=weeks, anchor_end=anchor)
    if isinstance(result, dict):
        result.pop("_activities", None)
    return result


@mcp.tool()
def get_report(
    days: int = 7, days_ago: int = 0, include_activities: bool = False
) -> Dict[str, Any]:
    """Rollable training report for a past day window (internal building block)."""
    if days < 1 or days > 90:
        return {"error": "days must be between 1 and 90"}

    try:
        anchor = compute_anchor_end(days_ago)
        start_date, end_date = window_bounds(days, days_ago)
    except ValueError as exc:
        return {"error": str(exc)}

    client, error = _get_client_or_error()
    if error:
        return error

    profile = get_profile()
    if isinstance(profile, dict) and profile.get("error"):
        return profile

    race_predictions = get_race_predictions()
    if isinstance(race_predictions, dict) and race_predictions.get("error"):
        return race_predictions

    personal_records = get_personal_records()
    if isinstance(personal_records, dict) and personal_records.get("error"):
        # Always soft-fail: PRs are optional athlete context. Auth/client failures
        # already abort earlier via profile / race_predictions / events.
        personal_records = {
            "records": [],
            "summary": str(personal_records.get("error")),
            "raw_error": personal_records,
        }

    events = get_events()
    if isinstance(events, dict) and events.get("error"):
        return events

    plan_result = _training_plan_table(client, events, anchor_end=anchor)
    if isinstance(plan_result, dict) and plan_result.get("error"):
        return plan_result

    training_plan, plan_activities = plan_result
    review_start, review_end = block_bounds(anchor)
    eval_end = date.today() if days_ago == 0 else review_end
    recent_activities = _recent_activity_summaries(
        plan_activities,
        window_start=review_start,
        window_end=eval_end,
    )
    _enrich_self_evaluations(
        client,
        recent_activities,
        plan_activities,
        review_start,
        eval_end,
    )

    report: Dict[str, Any] = {
        "window": {
            "days": days,
            "days_ago": days_ago,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "profile": profile,
        "race_predictions": race_predictions,
        "personal_records": personal_records,
        "events": events,
        "training_plan": training_plan,
    }
    if include_activities:
        report["activities"] = _activities_table(
            client, days=days, days_ago=days_ago, include_hr_zones=True
        )
    report["coaching_brief"] = build_coaching_brief(
        training_plan if isinstance(training_plan, list) else [],
        events if isinstance(events, dict) else None,
        recent_activities=recent_activities,
        personal_records=personal_records if isinstance(personal_records, dict) else None,
    )
    return report


@mcp.tool()
def get_coaching_brief(
    days_back: int = 7, include_activities: bool = False
) -> Dict[str, Any]:
    """Primary coach tool — fetch all Garmin data and a deterministic coaching brief.

    Returns profile, race predictions, events, training_plan (lookback + upcoming
    week rows), coaching_brief (review, assessment, next-week context with
    per-day weather, ready-to-read narrative, this week's written
    self-evaluation notes, session_targets for uploads), and optional
    activities. Call once per coaching turn.

    Upload each next_week_proposal session with the matching create_*_workout
    template. Threshold uses HR zone 4. Combine named templates with
    combine_workout_templates.
    """
    return get_report(
        days=days_back,
        days_ago=0,
        include_activities=include_activities,
    )


@mcp.resource("garmin://health")
def health() -> Dict[str, Any]:
    """Lightweight Garmin Connect reachability check (no weekly report)."""
    return _garmin_health_payload()


@mcp.tool()
def get_garmin_health() -> Dict[str, Any]:
    """Lightweight Garmin Connect reachability/auth check (no weekly report)."""
    return _garmin_health_payload()


@mcp.resource("garmin://weekly-report")
def weekly_report() -> Dict[str, Any]:
    """Default weekly review bundle (last 7 days). Alias for get_report."""
    return get_report(days=7, days_ago=0)


@mcp.resource("garmin://weekly-report/{days_back}")
def weekly_report_for_days(days_back: int) -> Dict[str, Any]:
    """Review bundle for a custom look-back window (days_back)."""
    days_back = max(1, min(days_back, 90))
    return get_report(days=days_back, days_ago=0)


@mcp.resource("garmin://report/{days}")
def report_for_days(days: int) -> Dict[str, Any]:
    return get_report(days=days, days_ago=0)


@mcp.tool()
def get_events(months_ahead: int = 12) -> Dict[str, Any]:
    """Upcoming Garmin calendar events, plus the latest event from the past 4 weeks.

    ``Garmin Events`` lists upcoming races only (same as before). When an event
    occurred within the last 28 days, ``latest_event`` carries its title, date,
    and target distance/duration from the calendar entry.
    """
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
    upcoming_rows: list[list[Any]] = []
    scan_rows: list[list[Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    def _append_event(event: dict[str, Any]) -> None:
        event_date_str = event.get("date")
        if not event_date_str:
            return
        try:
            event_date = date.fromisoformat(event_date_str)
        except ValueError:
            return
        title = (event.get("title") or "").strip()
        dedupe_key = (title.lower(), event_date_str)
        if dedupe_key in seen_keys:
            return
        seen_keys.add(dedupe_key)
        completion_target = event.get("completionTarget") or {}
        row = [
            title or event.get("title"),
            event.get("itemType"),
            event_date_str,
            completion_target.get("value"),
            completion_target.get("unit"),
            completion_target.get("unitType"),
        ]
        scan_rows.append(row)
        if event_date > today:
            upcoming_rows.append(row)

    # Upcoming list: forward from the current month.
    for offset in range(months_ahead):
        total_month = (start_month.month - 1) + offset
        year = start_month.year + total_month // 12
        month = total_month % 12 + 1
        calendar_payload = _call_optional(
            client, "get_scheduled_workouts", year=year, month=month
        )
        if not isinstance(calendar_payload, dict) or calendar_payload.get("error"):
            continue
        calendar_items = calendar_payload.get("calendarItems", [])
        if not isinstance(calendar_items, list):
            continue
        for event in calendar_items:
            if isinstance(event, dict) and event.get("itemType") == "event":
                _append_event(event)

    # Latest recent event: scan ~2 months back (covers the 4-week window).
    for offset in range(-2, 0):
        total_month = (start_month.month - 1) + offset
        year = start_month.year + total_month // 12
        month = total_month % 12 + 1
        calendar_payload = _call_optional(
            client, "get_scheduled_workouts", year=year, month=month
        )
        if not isinstance(calendar_payload, dict) or calendar_payload.get("error"):
            continue
        calendar_items = calendar_payload.get("calendarItems", [])
        if not isinstance(calendar_items, list):
            continue
        for event in calendar_items:
            if isinstance(event, dict) and event.get("itemType") == "event":
                _append_event(event)

    upcoming_rows.sort(key=lambda row: row[2])

    return {
        "latest_event": latest_event_within_days(scan_rows, today=today),
        "Garmin Events": {
            "Headers": event_columns,
            "Rows": upcoming_rows,
        },
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


def _pr_activity_type(item: dict[str, Any]) -> Any:
    activity_type = item.get("activityType")
    if isinstance(activity_type, dict):
        return activity_type.get("typeKey") or activity_type.get("typeId")
    return activity_type


def _pr_date(item: dict[str, Any]) -> str | None:
    for key in ("prStartTimeGMT", "startTimeGMT", "date", "calendarDate"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value[:10]
    return None


# Coaching card PRs only: 5K / 10K / half / marathon / longest run.
# Garmin Connect does not expose a standard 15K (or 1K/3K/20K) typeId; 15K is
# kept via label match if a payload ever includes it.
_PR_TYPE_META: dict[int, tuple[str, str]] = {
    3: ("5K", "seconds"),
    4: ("10K", "seconds"),
    5: ("Half Marathon", "seconds"),
    6: ("Marathon", "seconds"),
    7: ("Longest Run", "meters"),
}
_PR_INCLUDED_TYPE_IDS = frozenset(_PR_TYPE_META)
_PR_EXCLUDED_LABEL_HINTS = (
    "1k",
    "1 km",
    "3k",
    "3 km",
    "20k",
    "20 km",
    "1 mile",
    "1-mile",
    "1mi",
)
_PR_INCLUDED_LABEL_HINTS = (
    "5k",
    "10k",
    "15k",
    "half",
    "marathon",
    "longest run",
)
_PR_SORT_ORDER_BY_TYPE = {3: 0, 4: 1, 5: 3, 6: 4, 7: 5}
# 15K sits between 10K and half when matched by label only.
_PR_SORT_ORDER_BY_LABEL = (
    ("5k", 0),
    ("10k", 1),
    ("15k", 2),
    ("half", 3),
    ("marathon", 4),
    ("longest", 5),
)


def _pr_type_id(item: dict[str, Any]) -> int | None:
    raw = item.get("typeId")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _pr_label(item: dict[str, Any]) -> str:
    type_id = _pr_type_id(item)
    if type_id is not None and type_id in _PR_TYPE_META:
        return _PR_TYPE_META[type_id][0]
    for key in ("prType", "name", "activityName", "typeId"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return "PR"


def _label_has_token(label: str, token: str) -> bool:
    """Match distance tokens without substring false positives (5k vs 15k/25k)."""
    return re.search(rf"(?<!\d){re.escape(token)}\b", label, flags=re.IGNORECASE) is not None


def _pr_label_is_included(label: str) -> bool:
    label_l = label.lower()
    if any(_label_has_token(label_l, hint) for hint in _PR_EXCLUDED_LABEL_HINTS):
        return False
    if "longest" in label_l and "run" not in label_l:
        # Avoid longest ride / swim when typeId is missing.
        return False
    return any(_label_has_token(label_l, hint) for hint in _PR_INCLUDED_LABEL_HINTS)


def _include_personal_record(item: dict[str, Any], label: str, type_id: int | None) -> bool:
    """Keep coaching-relevant race PRs + longest run; drop short junk distances."""
    if type_id is not None:
        return type_id in _PR_INCLUDED_TYPE_IDS
    return _pr_label_is_included(label)


def _pr_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    type_id = row.get("type_id")
    if isinstance(type_id, int) and type_id in _PR_SORT_ORDER_BY_TYPE:
        return (_PR_SORT_ORDER_BY_TYPE[type_id], str(row.get("label") or ""))
    label_l = str(row.get("label") or "").lower()
    # Prefer more specific hints first (15k before 5k).
    for hint, rank in sorted(
        _PR_SORT_ORDER_BY_LABEL, key=lambda item: -len(item[0])
    ):
        if _label_has_token(label_l, hint):
            return (rank, str(row.get("label") or ""))
    return (50, str(row.get("label") or ""))


def _format_duration_seconds(secs: float) -> str:
    total = int(round(secs))
    if total < 0:
        return str(secs)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_pr_value(value: Any, label: str, type_id: Any = None) -> str:
    """Format Garmin PR values for coach-facing text (times / distances)."""
    if value is None:
        return "—"
    if not isinstance(value, (int, float)):
        return str(value)

    unit: str | None = None
    try:
        tid = int(type_id) if type_id is not None else None
    except (TypeError, ValueError):
        tid = None
    if tid is not None and tid in _PR_TYPE_META:
        unit = _PR_TYPE_META[tid][1]

    if unit == "seconds":
        return _format_duration_seconds(float(value))
    if unit == "meters":
        return f"{float(value) / 1000:.2f} km"

    label_l = label.lower()
    if "longest" in label_l or "distance" in label_l:
        return f"{float(value) / 1000:.2f} km"
    if any(
        _label_has_token(label_l, hint)
        for hint in ("5k", "10k", "15k", "half", "marathon")
    ):
        return _format_duration_seconds(float(value))
    return str(value)


def _normalize_personal_records(raw: Any) -> Dict[str, Any]:
    """Normalize Garmin personal-record payloads into a readable structure."""
    if isinstance(raw, dict) and raw.get("error"):
        return raw

    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        for key in ("personalRecords", "records", "prList", "itemList"):
            nested = raw.get(key)
            if isinstance(nested, list):
                items = nested
                break
        else:
            return {
                "raw": raw,
                "records": [],
                "summary": "Unexpected personal records shape",
            }
    else:
        return {
            "raw": raw,
            "records": [],
            "summary": "Unexpected personal records shape",
        }

    records: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = _pr_label(item)
        type_id = _pr_type_id(item)
        if not _include_personal_record(item, label, type_id):
            continue
        value = item.get("value")
        records.append(
            {
                "label": label,
                "value": value,
                "display_value": _format_pr_value(value, label, type_id),
                "activity_type": _pr_activity_type(item),
                "date": _pr_date(item),
                "type_id": type_id,
            }
        )

    # Stable coaching order: 5K → 10K → 15K → half → marathon → longest.
    records.sort(key=_pr_sort_key)

    return {
        "records": records,
        "summary": (
            f"{len(records)} personal record(s)"
            if records
            else "No personal records"
        ),
    }


@mcp.tool()
def get_personal_records() -> Dict[str, Any]:
    """Running personal records for coaching: 5K, 10K, half, marathon, longest run.

    Drops short/noise distances (1K, mile, steps, etc.). Garmin does not expose
    a standard 15K typeId; longest run distance is always included when present.
    """
    client, error = _get_client_or_error()
    if error:
        return error

    # garminconnect 0.3.6 exposes get_personal_record (singular).
    raw = _call_optional(client, "get_personal_record")
    if raw is None:
        return {
            "records": [],
            "summary": "Personal records not available from this Garmin client",
        }
    return _normalize_personal_records(raw)


def _upload_running_workout(client: Garmin, workout) -> Dict[str, Any]:
    result = _call_optional(client, "upload_running_workout", workout)
    if isinstance(result, dict) and result.get("error"):
        return result
    if not isinstance(result, dict):
        return {"error": "Workout upload did not return a response."}

    workout_id = extract_workout_id(result)
    return {
        "workoutId": workout_id,
        "workoutName": workout.workoutName,
        "estimatedDurationMinutes": round(workout.estimatedDurationInSecs / 60, 1),
        "upload": result,
    }


@mcp.tool()
def get_nutrition_cues(duration_minutes: int, intensity: str = "easy") -> Dict[str, Any]:
    """Return premade before/during/after eat and drink cues for a workout duration."""
    try:
        return lookup_nutrition_cues(duration_minutes, intensity=intensity)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_heart_rate_zones() -> Dict[str, Any]:
    """Return heart rate zones used by workout templates (Karvonen / HRR method)."""
    client, error = _get_client_or_error()
    if error:
        return error
    return resolve_hr_context(client, get_profile())


@mcp.tool()
def get_workouts(start: int = 0, limit: int = 20) -> Dict[str, Any]:
    """List saved Garmin workout templates from the workout library."""
    client, error = _get_client_or_error()
    if error:
        return error

    workouts = _call_optional(client, "get_workouts", start=start, limit=limit)
    if isinstance(workouts, dict) and workouts.get("error"):
        return workouts
    if not isinstance(workouts, list):
        return {"error": "No workouts returned from Garmin"}

    rows = []
    for workout in workouts:
        if not isinstance(workout, dict):
            continue
        rows.append(
            [
                workout.get("workoutId"),
                workout.get("workoutName"),
                round((workout.get("estimatedDurationInSecs") or 0) / 60, 1),
                workout.get("sportType", {}).get("sportTypeKey"),
            ]
        )

    return {
        "Garmin Workouts": {
            "Headers": ["id", "name", "duration_min", "sport"],
            "Rows": rows,
        }
    }


def _validate_workout_date(workout_date: str) -> Optional[Dict[str, Any]]:
    """Return a structured error dict if workout_date is not ISO YYYY-MM-DD."""
    try:
        date.fromisoformat(workout_date)
    except (ValueError, TypeError):
        return {"error": "workout_date must be an ISO date (YYYY-MM-DD)"}
    return None


def _schedule_existing(client: Garmin, workout_id: int, workout_date: str) -> Dict[str, Any]:
    """Schedule an uploaded workout on a date, skipping duplicate calendar entries."""
    if hasattr(client, "schedule_workout"):
        existing = _find_scheduled_workout(client, workout_id, workout_date)
        if existing is not None:
            return {
                "workoutId": workout_id,
                "date": workout_date,
                "alreadyScheduled": True,
                "schedule": existing,
            }

    result = _call_optional(client, "schedule_workout", workout_id, workout_date)
    if isinstance(result, dict) and result.get("error"):
        return result
    return {
        "workoutId": workout_id,
        "date": workout_date,
        "schedule": result,
    }


@mcp.tool()
def schedule_workout(workout_id: int, workout_date: str) -> Dict[str, Any]:
    """Schedule an existing workout template on a calendar date (YYYY-MM-DD)."""
    client, error = _get_client_or_error()
    if error:
        return error

    date_error = _validate_workout_date(workout_date)
    if date_error:
        return date_error

    return _schedule_existing(client, workout_id, workout_date)


@mcp.tool()
def list_workout_templates() -> Dict[str, Any]:
    """List built-in workout templates and the heart rate zones they use."""
    return {
        "templates": [
            {
                "template": template,
                "description": TEMPLATE_DESCRIPTIONS[template],
            }
            for template in TEMPLATE_TYPES
        ],
        "combineHint": (
            "Use combine_workout_templates with segments like "
            '[{"template": "base", "params": {"duration_minutes": 20}}, '
            '{"template": "sprint", "params": {"repetitions": 6}}].'
        ),
    }


def _create_from_template(
    template: str,
    name: str,
    params: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

    if workout_date is not None:
        date_error = _validate_workout_date(workout_date)
        if date_error:
            return date_error

    try:
        running_workout = build_template_workout(
            name,
            template,
            params=params,
            description=description or TEMPLATE_DESCRIPTIONS.get(template),
            include_nutrition_cues=include_nutrition_cues,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    upload_result = _upload_running_workout(client, running_workout)
    if upload_result.get("error"):
        return upload_result

    upload_result["template"] = template
    upload_result["params"] = params or {}
    upload_result["heartRateZones"] = resolve_hr_context(client, get_profile()).get("zones")
    if include_nutrition_cues:
        upload_result["nutritionCues"] = lookup_nutrition_cues(
            estimate_template_duration_minutes(template, params),
            intensity=intensity_for_template(template),
        )

    workout_id = upload_result.get("workoutId")
    if workout_date is not None and workout_id is not None:
        upload_result["schedule"] = _schedule_existing(
            client, int(workout_id), workout_date
        )

    return upload_result


@mcp.tool()
def create_base_workout(
    duration_minutes: int = 30,
    name: str = "Base Run",
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a single-step base aerobic run (HR zone 2). Pass workout_date
    (YYYY-MM-DD) to also schedule it on the calendar in the same call."""
    return _create_from_template(
        "base",
        name,
        params={"duration_minutes": duration_minutes},
        include_nutrition_cues=include_nutrition_cues,
        workout_date=workout_date,
    )


@mcp.tool()
def create_long_run_workout(
    duration_minutes: int = 90,
    name: str = "Long Run",
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a single-step long easy run (HR zone 2). Pass workout_date
    (YYYY-MM-DD) to also schedule it in the same call."""
    return _create_from_template(
        "long_run",
        name,
        params={"duration_minutes": duration_minutes},
        include_nutrition_cues=include_nutrition_cues,
        workout_date=workout_date,
    )


@mcp.tool()
def create_recovery_workout(
    duration_minutes: int = 25,
    name: str = "Recovery Run",
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a short recovery jog (HR zone 1). Pass workout_date (YYYY-MM-DD)
    to also schedule it in the same call."""
    return _create_from_template(
        "recovery",
        name,
        params={"duration_minutes": duration_minutes},
        include_nutrition_cues=include_nutrition_cues,
        workout_date=workout_date,
    )


@mcp.tool()
def create_threshold_workout(
    repetitions: int = 4,
    interval_minutes: int = 5,
    recovery_minutes: int = 2,
    warmup_minutes: int = 10,
    cooldown_minutes: int = 10,
    name: str = "Threshold Run",
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create lactate-threshold repeats with warmup and cooldown (efforts in HR
    zone 4). Use this tool for threshold sessions; keep the HR zone 4 target.
    Pass workout_date (YYYY-MM-DD) to also schedule it in the same call."""
    return _create_from_template(
        "threshold",
        name,
        params={
            "repetitions": repetitions,
            "interval_minutes": interval_minutes,
            "recovery_minutes": recovery_minutes,
            "warmup_minutes": warmup_minutes,
            "cooldown_minutes": cooldown_minutes,
        },
        include_nutrition_cues=include_nutrition_cues,
        workout_date=workout_date,
    )


@mcp.tool()
def create_sprint_workout(
    repetitions: int = 6,
    sprint_distance_meters: int = 100,
    target_speed_mps_min: float = 5.5,
    target_speed_mps_max: float = 6.5,
    recovery_seconds: int = 90,
    warmup_minutes: int = 15,
    cooldown_minutes: int = 10,
    name: str = "Sprint Intervals",
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create short sprint repeats with jog recoveries.

    Each effort ends at ``sprint_distance_meters`` with a Garmin speed.zone
    target (``target_speed_mps_min``–``target_speed_mps_max`` in m/s). Warmup,
    recovery, and cooldown stay time-based with HR zones. Pace on the reps
    applies to sprints only, not threshold. Pass workout_date (YYYY-MM-DD)
    to also schedule it in the same call.
    """
    return _create_from_template(
        "sprint",
        name,
        params={
            "repetitions": repetitions,
            "sprint_distance_meters": sprint_distance_meters,
            "target_speed_mps_min": target_speed_mps_min,
            "target_speed_mps_max": target_speed_mps_max,
            "recovery_seconds": recovery_seconds,
            "warmup_minutes": warmup_minutes,
            "cooldown_minutes": cooldown_minutes,
        },
        include_nutrition_cues=include_nutrition_cues,
        workout_date=workout_date,
    )


@mcp.tool()
def create_hill_repeats_workout(
    repetitions: int = 6,
    sprint_distance_meters: int = 100,
    target_speed_mps_min: float = 5.5,
    target_speed_mps_max: float = 6.5,
    recovery_seconds: int = 90,
    warmup_minutes: int = 15,
    cooldown_minutes: int = 10,
    name: str = "Hill Repeats",
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create hill repeats — distance sprints meant to be run uphill.

    Same structure as ``create_sprint_workout`` (distance + speed targets on
    efforts). Run them on a hill. Pass workout_date (YYYY-MM-DD) to also
    schedule it in the same call.
    """
    return _create_from_template(
        "hill_repeats",
        name,
        params={
            "repetitions": repetitions,
            "sprint_distance_meters": sprint_distance_meters,
            "target_speed_mps_min": target_speed_mps_min,
            "target_speed_mps_max": target_speed_mps_max,
            "recovery_seconds": recovery_seconds,
            "warmup_minutes": warmup_minutes,
            "cooldown_minutes": cooldown_minutes,
        },
        include_nutrition_cues=include_nutrition_cues,
        workout_date=workout_date,
    )


@mcp.tool()
def create_weighted_pack_workout(
    duration_minutes: int = 45,
    name: str = "Weighted Pack Run",
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a base aerobic run (HR zone 2) to be run carrying a loaded pack
    (rucking). Same structure as a base run. Pass workout_date (YYYY-MM-DD) to
    also schedule it in the same call."""
    return _create_from_template(
        "weighted_pack",
        name,
        params={"duration_minutes": duration_minutes},
        include_nutrition_cues=include_nutrition_cues,
        workout_date=workout_date,
    )


def _validate_combine_segments(
    segments: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Require named template segments; reject freeform step lists."""
    named_template_error = {
        "error": (
            "combine_workout_templates only accepts named template "
            'segments like {"template": "base", "params": '
            '{"duration_minutes": 20}}. Use create_*_workout for a '
            "single session."
        )
    }
    if not segments:
        return {"error": "Provide at least one template segment to combine."}
    for segment in segments:
        if not isinstance(segment, dict):
            return {"error": "Each segment must be an object with a template key."}
        if "steps" in segment or not segment.get("template"):
            return named_template_error
    return None


@mcp.tool()
def combine_workout_templates(
    name: str,
    segments: List[Dict[str, Any]],
    description: Optional[str] = None,
    include_nutrition_cues: bool = False,
    workout_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Combine named workout templates into one session (for example easy + strides).

    Each segment must name a template, e.g.:
    - {"template": "base", "params": {"duration_minutes": 20}}
    - {"template": "sprint", "params": {"repetitions": 6}}

    Not a freeform step builder. Use create_*_workout for a single template.
    Pass workout_date (YYYY-MM-DD) to also schedule it in the same call.
    """
    client, error = _get_client_or_error()
    if error:
        return error

    segment_error = _validate_combine_segments(segments)
    if segment_error:
        return segment_error

    if workout_date is not None:
        date_error = _validate_workout_date(workout_date)
        if date_error:
            return date_error

    try:
        running_workout = build_combined_workout(
            name,
            segments,
            description=description,
            include_nutrition_cues=include_nutrition_cues,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    upload_result = _upload_running_workout(client, running_workout)
    if upload_result.get("error"):
        return upload_result

    upload_result["segments"] = segments
    upload_result["heartRateZones"] = resolve_hr_context(client, get_profile()).get("zones")
    if include_nutrition_cues:
        primary_template = str(segments[0].get("template", "base")) if segments else "base"
        upload_result["nutritionCues"] = lookup_nutrition_cues(
            estimate_combined_duration_minutes(segments),
            intensity=intensity_for_template(primary_template),
        )

    workout_id = upload_result.get("workoutId")
    if workout_date is not None and workout_id is not None:
        upload_result["schedule"] = _schedule_existing(
            client, int(workout_id), workout_date
        )

    return upload_result

mount_rest_routes(mcp)


if __name__ == "__main__":
    # Streamable HTTP avoids Odysseus SSE stale-session failures (list_tools works,
    # call_tool dies on a closed anyio stream). Odysseus: transport "http",
    # URL http://garmin-mcp:8000/mcp
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)  # type: ignore[arg-type]
