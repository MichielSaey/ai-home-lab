import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from hr_zones import resolve_hr_context
from nutrition_matrix import (
    get_nutrition_cues as lookup_nutrition_cues,
    intensity_for_template,
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
from workout_builder import build_running_workout, extract_workout_id
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

_CLIENT: Optional[Garmin] = None
_CLIENT_ERROR: Optional[Dict[str, Any]] = None

COACH_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "coach_prompt.md"

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
    if days < 1:
        raise ValueError("days must be at least 1")
    if days_ago < 0:
        raise ValueError("days_ago must be zero or positive")

    end_date = date.today() - timedelta(days=days_ago)
    start_date = end_date - timedelta(days=days - 1)
    return start_date, end_date


def _load_coach_prompt() -> str:
    if not COACH_PROMPT_PATH.exists():
        return "You are a Garmin running coach. Follow the 80/20 rule: 80% easy, 20% hard."
    return COACH_PROMPT_PATH.read_text(encoding="utf-8")


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
    days_back: int = 7,
    *,
    days: Optional[int] = None,
    days_ago: int = 0,
    include_hr_zones: bool = True,
) -> Dict[str, Any] | dict[str, Any]:
    if days is not None:
        window_start, window_end = _report_window(days, days_ago)
        start_date = window_start.isoformat()
        end_date = window_end.isoformat()
    else:
        today = date.today()
        start_date = (today - timedelta(days=days_back)).isoformat()
        end_date = today.isoformat()

    activities = _running_activities_in_range(client, start_date, end_date)
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

    payload: Dict[str, Any] = {
        "Garmin Activities": {
            "Headers": headers,
            "Rows": rows,
        }
    }
    if days is not None:
        payload["window"] = {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "days_ago": days_ago,
        }
    return payload


def _weekly_stats_table(
    client: Garmin, weeks: int = 4, *, end_date: Optional[date] = None
) -> Dict[str, Any] | dict[str, Any]:
    report_end = end_date or date.today()
    lookback_days = weeks * 7 - 1
    activities = _running_activities_in_range(
        client,
        (report_end - timedelta(days=lookback_days)).isoformat(),
        report_end.isoformat(),
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
            "Rows": weekly_stats_rows(activities, activity_zones, report_end, num_blocks=weeks),
        }
    }


def _training_plan_table(
    client: Garmin,
    events: Dict[str, Any],
    weeks: int = 4,
    *,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    stats = _weekly_stats_table(client, weeks=weeks, end_date=end_date)
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
    """Running activities in a date window. Use days/days_ago for rollable windows."""
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
    """Weekly running distance and HR zone rollups (one row per calendar week)."""
    client, error = _get_client_or_error()
    if error:
        return error
    report_end: Optional[date] = None
    if end_date is not None:
        try:
            report_end = date.fromisoformat(end_date)
        except ValueError:
            return {"error": "end_date must be an ISO date (YYYY-MM-DD)"}
    return _weekly_stats_table(client, weeks=weeks, end_date=report_end)


@mcp.tool()
def get_report(
    days: int = 7, days_ago: int = 0, include_activities: bool = False
) -> Dict[str, Any]:
    """Build a rollable Garmin training report for a past window of days."""
    if days < 1 or days > 90:
        return {"error": "days must be between 1 and 90"}

    try:
        start_date, end_date = _report_window(days, days_ago)
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

    events = get_events()
    if isinstance(events, dict) and events.get("error"):
        return events

    training_plan = _training_plan_table(client, events, end_date=end_date)
    if isinstance(training_plan, dict) and training_plan.get("error"):
        return training_plan

    report: Dict[str, Any] = {
        "window": {
            "days": days,
            "days_ago": days_ago,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "profile": profile,
        "race_predictions": race_predictions,
        "events": events,
        "training_plan": training_plan,
    }
    if include_activities:
        report["activities"] = _activities_table(
            client, days=days, days_ago=days_ago, include_hr_zones=True
        )
    return report


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
    return get_report(
        days=days_back,
        days_ago=0,
        include_activities=include_activities,
    )


@mcp.resource("garmin://health")
def health() -> Dict[str, Any]:
    """Lightweight Garmin Connect reachability check (no weekly report)."""
    return _garmin_health_payload()


@mcp.resource("garmin://coach-prompt")
def coach_prompt() -> str:
    """Coach instructions including 80/20 polarized training rules and session workflow."""
    return _load_coach_prompt()


@mcp.resource("garmin://health")
def health() -> Dict[str, Any]:
    """Lightweight Garmin Connect reachability check (no weekly report)."""
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


@mcp.tool()
def workout(
    name: str,
    steps: List[Dict[str, Any]],
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a running workout from an ordered list of adjacent steps.

    Each step is a dict with:
    - type: warmup | interval | recovery | cooldown | repeat
    - duration_minutes: float (required for regular steps)
    - workout_type: optional preset zone key (easy, tempo, threshold, strides, sprint, ...)
    - heart_rate_zone: optional Garmin zone number 1-5 (overrides workout_type)
    - iterations + steps: required for repeat blocks

    Heart rate targets are set automatically unless heart_rate_zone is provided.
    """
    client, error = _get_client_or_error()
    if error:
        return error

    try:
        running_workout = build_running_workout(name, steps, description=description)
    except ValueError as exc:
        return {"error": str(exc)}

    upload_result = _upload_running_workout(client, running_workout)
    if upload_result.get("error"):
        return upload_result

    upload_result["heartRateZones"] = resolve_hr_context(client, get_profile()).get("zones")
    return upload_result


@mcp.tool()
def schedule_workout(workout_id: int, workout_date: str) -> Dict[str, Any]:
    """Schedule an existing workout template on a calendar date (YYYY-MM-DD)."""
    client, error = _get_client_or_error()
    if error:
        return error

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
            '[{"template": "easy", "params": {"duration_minutes": 20}}, '
            '{"template": "strides", "params": {"count": 6}}].'
        ),
    }


def _create_from_template(
    template: str,
    name: str,
    params: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    client, error = _get_client_or_error()
    if error:
        return error

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
    return upload_result


@mcp.tool()
def create_easy_workout(
    duration_minutes: int = 30,
    name: str = "Easy Run",
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Create a single-step easy aerobic run (HR zone 2)."""
    return _create_from_template(
        "easy",
        name,
        params={"duration_minutes": duration_minutes},
        include_nutrition_cues=include_nutrition_cues,
    )


@mcp.tool()
def create_long_run_workout(
    duration_minutes: int = 90,
    name: str = "Long Run",
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Create a single-step long easy run (HR zone 2)."""
    return _create_from_template(
        "long_run",
        name,
        params={"duration_minutes": duration_minutes},
        include_nutrition_cues=include_nutrition_cues,
    )


@mcp.tool()
def create_recovery_workout(
    duration_minutes: int = 25,
    name: str = "Recovery Run",
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Create a short recovery jog (HR zone 1)."""
    return _create_from_template(
        "recovery",
        name,
        params={"duration_minutes": duration_minutes},
        include_nutrition_cues=include_nutrition_cues,
    )


@mcp.tool()
def create_tempo_workout(
    duration_minutes: int = 20,
    warmup_minutes: int = 10,
    cooldown_minutes: int = 10,
    name: str = "Tempo Run",
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Create a tempo run with warmup and cooldown (main block HR zone 3)."""
    return _create_from_template(
        "tempo",
        name,
        params={
            "duration_minutes": duration_minutes,
            "warmup_minutes": warmup_minutes,
            "cooldown_minutes": cooldown_minutes,
        },
        include_nutrition_cues=include_nutrition_cues,
    )


@mcp.tool()
def create_threshold_workout(
    duration_minutes: int = 20,
    warmup_minutes: int = 10,
    cooldown_minutes: int = 10,
    name: str = "Threshold Run",
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Create a lactate-threshold run with warmup and cooldown (main block HR zone 4)."""
    return _create_from_template(
        "threshold",
        name,
        params={
            "duration_minutes": duration_minutes,
            "warmup_minutes": warmup_minutes,
            "cooldown_minutes": cooldown_minutes,
        },
        include_nutrition_cues=include_nutrition_cues,
    )


@mcp.tool()
def create_strides_workout(
    count: int = 6,
    stride_seconds: int = 20,
    recovery_seconds: int = 60,
    warmup_minutes: int = 15,
    cooldown_minutes: int = 10,
    name: str = "Strides",
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Create a strides session with easy warmup/cooldown (efforts in HR zone 5)."""
    return _create_from_template(
        "strides",
        name,
        params={
            "count": count,
            "stride_seconds": stride_seconds,
            "recovery_seconds": recovery_seconds,
            "warmup_minutes": warmup_minutes,
            "cooldown_minutes": cooldown_minutes,
        },
        include_nutrition_cues=include_nutrition_cues,
    )


@mcp.tool()
def create_sprint_workout(
    repetitions: int = 6,
    sprint_seconds: int = 30,
    recovery_seconds: int = 90,
    warmup_minutes: int = 15,
    cooldown_minutes: int = 10,
    name: str = "Sprint Intervals",
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Create short sprint repeats with jog recoveries (efforts in HR zone 5)."""
    return _create_from_template(
        "sprint",
        name,
        params={
            "repetitions": repetitions,
            "sprint_seconds": sprint_seconds,
            "recovery_seconds": recovery_seconds,
            "warmup_minutes": warmup_minutes,
            "cooldown_minutes": cooldown_minutes,
        },
        include_nutrition_cues=include_nutrition_cues,
    )


@mcp.tool()
def combine_workout_templates(
    name: str,
    segments: List[Dict[str, Any]],
    description: Optional[str] = None,
    include_nutrition_cues: bool = False,
) -> Dict[str, Any]:
    """Combine multiple workout templates into one session.

    Each segment is either:
    - {"template": "easy", "params": {"duration_minutes": 20}}
    - {"template": "strides", "params": {"count": 6}}
    - {"steps": [...]} with explicit workout() step objects

    Example: easy 20 min + strides + easy 10 min cooldown block.
    """
    client, error = _get_client_or_error()
    if error:
        return error

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
        primary_template = str(segments[0].get("template", "easy")) if segments else "easy"
        upload_result["nutritionCues"] = lookup_nutrition_cues(
            estimate_combined_duration_minutes(segments),
            intensity=intensity_for_template(primary_template),
        )
    return upload_result

mount_rest_routes(mcp)


if __name__ == "__main__":
    # Streamable HTTP avoids Odysseus SSE stale-session failures (list_tools works,
    # call_tool dies on a closed anyio stream). Odysseus: transport "http",
    # URL http://garmin-mcp:8000/mcp
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)  # type: ignore[arg-type]
