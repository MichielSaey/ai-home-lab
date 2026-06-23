"""REST shim routes for n8n HTTP access alongside FastMCP SSE."""

from typing import Any, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from errors import (
    AUTH_FAILED,
    CONNECTION_ERROR,
    MISSING_CREDENTIALS,
    NOT_INITIALIZED,
    UNKNOWN,
)


def http_status_for_error(code: str) -> int:
    if code in (AUTH_FAILED, MISSING_CREDENTIALS):
        return 401
    if code in (CONNECTION_ERROR, NOT_INITIALIZED):
        return 503
    return 500


def is_structured_error(payload: Any) -> bool:
    return isinstance(payload, dict) and "code" in payload and "message" in payload


def response_from_structured_error(error: Dict[str, Any]) -> JSONResponse:
    status = http_status_for_error(error.get("code", UNKNOWN))
    return JSONResponse(error, status_code=status)


def response_from_health(payload: Dict[str, Any]) -> JSONResponse:
    if payload.get("status") == "ok":
        return JSONResponse(payload, status_code=200)
    garmin = payload.get("garmin", {})
    if is_structured_error(garmin):
        status = http_status_for_error(garmin.get("code", UNKNOWN))
        return JSONResponse(payload, status_code=status)
    return JSONResponse(payload, status_code=500)


def parse_days_back(raw: Optional[str]) -> int:
    if raw is None:
        return 7
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("days_back must be an integer between 1 and 90") from exc
    if value < 1 or value > 90:
        raise ValueError("days_back must be an integer between 1 and 90")
    return value


def parse_weeks(raw: Optional[str]) -> int:
    if raw is None:
        return 4
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("weeks must be an integer between 1 and 12") from exc
    if value < 1 or value > 12:
        raise ValueError("weeks must be an integer between 1 and 12")
    return value


def parse_include_activities(raw: Optional[str]) -> bool:
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    raise ValueError("include_activities must be a boolean")


async def health_handler(request: Request) -> Response:
    import server

    return response_from_health(server.health())


async def weekly_report_handler(request: Request) -> Response:
    import server

    try:
        days_back = parse_days_back(request.query_params.get("days_back"))
        include_activities = parse_include_activities(
            request.query_params.get("include_activities")
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    result = server.get_weekly_report(
        days_back=days_back,
        include_activities=include_activities,
    )
    if is_structured_error(result):
        return response_from_structured_error(result)
    return JSONResponse(result, status_code=200)


async def training_plan_handler(request: Request) -> Response:
    import server

    try:
        weeks = parse_weeks(request.query_params.get("weeks"))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    result = server.get_training_plan(weeks=weeks)
    if is_structured_error(result):
        return response_from_structured_error(result)
    return JSONResponse(result, status_code=200)


def mount_rest_routes(mcp_instance: Any) -> None:
    """Register REST shim routes on the same Starlette app as FastMCP SSE."""
    mcp_instance.custom_route("/health", methods=["GET"])(health_handler)
    mcp_instance.custom_route("/weekly-report", methods=["GET"])(weekly_report_handler)
    mcp_instance.custom_route("/training-plan", methods=["GET"])(training_plan_handler)
