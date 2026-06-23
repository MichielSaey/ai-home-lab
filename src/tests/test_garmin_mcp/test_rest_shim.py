from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

import rest_shim
import server
from errors import (
    AUTH_FAILED,
    CONNECTION_ERROR,
    MISSING_CREDENTIALS,
    NOT_INITIALIZED,
    UNKNOWN,
    structured_error,
)


@pytest.fixture(autouse=True)
def reset_client_state() -> None:
    server._CLIENT = None
    server._CLIENT_ERROR = None
    yield
    server._CLIENT = None
    server._CLIENT_ERROR = None


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.mcp.sse_app())


def test_http_status_for_error_mapping() -> None:
    assert rest_shim.http_status_for_error(AUTH_FAILED) == 401
    assert rest_shim.http_status_for_error(MISSING_CREDENTIALS) == 401
    assert rest_shim.http_status_for_error(CONNECTION_ERROR) == 503
    assert rest_shim.http_status_for_error(NOT_INITIALIZED) == 503
    assert rest_shim.http_status_for_error(UNKNOWN) == 500


def test_parse_days_back_defaults_and_clamps() -> None:
    assert rest_shim.parse_days_back(None) == 7
    assert rest_shim.parse_days_back("14") == 14
    assert rest_shim.parse_days_back("1") == 1
    assert rest_shim.parse_days_back("90") == 90

    with pytest.raises(ValueError, match="days_back"):
        rest_shim.parse_days_back("0")
    with pytest.raises(ValueError, match="days_back"):
        rest_shim.parse_days_back("91")
    with pytest.raises(ValueError, match="days_back"):
        rest_shim.parse_days_back("abc")


def test_parse_weeks_defaults_and_clamps() -> None:
    assert rest_shim.parse_weeks(None) == 4
    assert rest_shim.parse_weeks("8") == 8
    assert rest_shim.parse_weeks("1") == 1
    assert rest_shim.parse_weeks("12") == 12

    with pytest.raises(ValueError, match="weeks"):
        rest_shim.parse_weeks("0")
    with pytest.raises(ValueError, match="weeks"):
        rest_shim.parse_weeks("13")
    with pytest.raises(ValueError, match="weeks"):
        rest_shim.parse_weeks("abc")


def test_parse_include_activities() -> None:
    assert rest_shim.parse_include_activities(None) is False
    assert rest_shim.parse_include_activities("true") is True
    assert rest_shim.parse_include_activities("1") is True
    assert rest_shim.parse_include_activities("false") is False
    assert rest_shim.parse_include_activities("0") is False

    with pytest.raises(ValueError, match="include_activities"):
        rest_shim.parse_include_activities("maybe")


def test_get_health_ok(client: TestClient) -> None:
    payload = {
        "status": "ok",
        "garmin": {"reachable": True, "authenticated": True},
        "checkedAt": "2026-06-18T12:00:00+00:00",
    }

    with patch.object(server, "health", return_value=payload):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == payload


def test_get_health_auth_error_returns_401(client: TestClient) -> None:
    payload = {
        "status": "error",
        "garmin": structured_error(AUTH_FAILED, "Invalid credentials", retryable=False),
        "checkedAt": "2026-06-18T12:00:00+00:00",
    }

    with patch.object(server, "health", return_value=payload):
        response = client.get("/health")

    assert response.status_code == 401
    assert response.json()["garmin"]["code"] == AUTH_FAILED


def test_get_health_connection_error_returns_503(client: TestClient) -> None:
    payload = {
        "status": "error",
        "garmin": structured_error(CONNECTION_ERROR, "Service unavailable", retryable=True),
        "checkedAt": "2026-06-18T12:00:00+00:00",
    }

    with patch.object(server, "health", return_value=payload):
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["garmin"]["code"] == CONNECTION_ERROR


def test_get_health_missing_credentials_returns_401(client: TestClient) -> None:
    with patch.object(server, "DEFAULT_GARMIN_USERNAME", None), patch.object(
        server, "DEFAULT_GARMIN_PASSWORD", None
    ):
        response = client.get("/health")

    assert response.status_code == 401
    assert response.json()["garmin"]["code"] == MISSING_CREDENTIALS


def test_get_weekly_report_success(client: TestClient) -> None:
    report = {
        "profile": {"weight": 70},
        "race_predictions": {},
        "events": {},
        "training_plan": [{"week": 1}],
    }

    with patch.object(server, "get_weekly_report", return_value=report) as get_weekly_report:
        response = client.get("/weekly-report?days_back=14&include_activities=true")

    assert response.status_code == 200
    assert response.json() == report
    get_weekly_report.assert_called_once_with(days_back=14, include_activities=True)


def test_get_weekly_report_defaults(client: TestClient) -> None:
    report = {"profile": {}, "training_plan": []}

    with patch.object(server, "get_weekly_report", return_value=report) as get_weekly_report:
        response = client.get("/weekly-report")

    assert response.status_code == 200
    get_weekly_report.assert_called_once_with(days_back=7, include_activities=False)


def test_get_weekly_report_structured_error_returns_503(client: TestClient) -> None:
    error = structured_error(NOT_INITIALIZED, "Garmin client not initialized.", retryable=True)

    with patch.object(server, "get_weekly_report", return_value=error):
        response = client.get("/weekly-report")

    assert response.status_code == 503
    assert response.json()["code"] == NOT_INITIALIZED


def test_get_weekly_report_unknown_error_returns_500(client: TestClient) -> None:
    error = structured_error(UNKNOWN, "Unexpected failure", retryable=True)

    with patch.object(server, "get_weekly_report", return_value=error):
        response = client.get("/weekly-report")

    assert response.status_code == 500
    assert response.json()["code"] == UNKNOWN


def test_get_weekly_report_invalid_query_params_return_400(client: TestClient) -> None:
    response = client.get("/weekly-report?days_back=0")
    assert response.status_code == 400
    assert "days_back" in response.json()["error"]

    response = client.get("/weekly-report?include_activities=maybe")
    assert response.status_code == 400
    assert "include_activities" in response.json()["error"]


def test_get_training_plan_success(client: TestClient) -> None:
    plan = [{"week": 1, "phase": "base"}]

    with patch.object(server, "get_training_plan", return_value=plan) as get_training_plan:
        response = client.get("/training-plan?weeks=4")

    assert response.status_code == 200
    assert response.json() == plan
    get_training_plan.assert_called_once_with(weeks=4)


def test_get_training_plan_defaults(client: TestClient) -> None:
    plan: list[dict[str, object]] = []

    with patch.object(server, "get_training_plan", return_value=plan) as get_training_plan:
        response = client.get("/training-plan")

    assert response.status_code == 200
    get_training_plan.assert_called_once_with(weeks=4)


def test_get_training_plan_structured_error(client: TestClient) -> None:
    error = structured_error(CONNECTION_ERROR, "Service unavailable", retryable=True)

    with patch.object(server, "get_training_plan", return_value=error):
        response = client.get("/training-plan")

    assert response.status_code == 503
    assert response.json()["code"] == CONNECTION_ERROR


def test_get_training_plan_invalid_weeks_returns_400(client: TestClient) -> None:
    response = client.get("/training-plan?weeks=0")
    assert response.status_code == 400
    assert "weeks" in response.json()["error"]


def test_rest_routes_mounted_on_sse_app(client: TestClient) -> None:
    paths = {getattr(route, "path", None) for route in server.mcp.sse_app().routes}
    assert "/health" in paths
    assert "/weekly-report" in paths
    assert "/training-plan" in paths
    assert "/sse" in paths
