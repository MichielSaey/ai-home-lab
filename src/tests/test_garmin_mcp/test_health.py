from unittest.mock import MagicMock, patch

import pytest
from garminconnect import GarminConnectAuthenticationError, GarminConnectConnectionError

import server
from errors import (
    AUTH_FAILED,
    CONNECTION_ERROR,
    MISSING_CREDENTIALS,
    NOT_INITIALIZED,
    structured_error,
)


@pytest.fixture(autouse=True)
def reset_client_state() -> None:
    server._CLIENT = None
    server._CLIENT_ERROR = None
    yield
    server._CLIENT = None
    server._CLIENT_ERROR = None


def test_structured_error_includes_backward_compatible_key() -> None:
    error = structured_error(
        MISSING_CREDENTIALS,
        "Missing Garmin credentials.",
        retryable=False,
    )

    assert error["code"] == MISSING_CREDENTIALS
    assert error["message"] == "Missing Garmin credentials."
    assert error["retryable"] is False
    assert error["error"] == "Missing Garmin credentials."


def test_get_client_or_error_missing_credentials() -> None:
    with patch.object(server, "DEFAULT_GARMIN_USERNAME", None), patch.object(
        server, "DEFAULT_GARMIN_PASSWORD", None
    ):
        client, error = server._get_client_or_error()

    assert client is None
    assert error is not None
    assert error["code"] == MISSING_CREDENTIALS
    assert error["retryable"] is False
    assert error["error"] == error["message"]


def test_get_client_or_error_auth_failed() -> None:
    with (
        patch.object(server, "DEFAULT_GARMIN_USERNAME", "user@example.com"),
        patch.object(server, "DEFAULT_GARMIN_PASSWORD", "secret"),
        patch.object(
            server.Garmin,
            "login",
            side_effect=GarminConnectAuthenticationError("Invalid credentials"),
        ),
    ):
        client, error = server._get_client_or_error()

    assert client is None
    assert error is not None
    assert error["code"] == AUTH_FAILED
    assert error["retryable"] is False
    assert "Invalid credentials" in error["message"]


def test_get_client_or_error_connection_error() -> None:
    with (
        patch.object(server, "DEFAULT_GARMIN_USERNAME", "user@example.com"),
        patch.object(server, "DEFAULT_GARMIN_PASSWORD", "secret"),
        patch.object(
            server.Garmin,
            "login",
            side_effect=GarminConnectConnectionError("Service unavailable"),
        ),
    ):
        client, error = server._get_client_or_error()

    assert client is None
    assert error is not None
    assert error["code"] == CONNECTION_ERROR
    assert error["retryable"] is True


def test_get_client_or_error_not_initialized() -> None:
    with (
        patch.object(server, "DEFAULT_GARMIN_USERNAME", "user@example.com"),
        patch.object(server, "DEFAULT_GARMIN_PASSWORD", "secret"),
        patch.object(server, "_init_client"),
    ):
        client, error = server._get_client_or_error()

    assert client is None
    assert error is not None
    assert error["code"] == NOT_INITIALIZED
    assert error["retryable"] is True


def test_health_ok_when_garmin_reachable() -> None:
    mock_client = MagicMock()
    mock_client.get_user_profile.return_value = {"userData": {"displayName": "Runner"}}

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.health()

    assert result["status"] == "ok"
    assert result["garmin"] == {"reachable": True, "authenticated": True}
    assert result["checkedAt"].endswith("+00:00")


def test_health_error_when_credentials_missing() -> None:
    with patch.object(server, "DEFAULT_GARMIN_USERNAME", None), patch.object(
        server, "DEFAULT_GARMIN_PASSWORD", None
    ):
        result = server.health()

    assert result["status"] == "error"
    assert result["garmin"]["code"] == MISSING_CREDENTIALS
    assert result["garmin"]["retryable"] is False
    assert result["checkedAt"].endswith("+00:00")


def test_health_error_when_probe_fails() -> None:
    mock_client = MagicMock()
    mock_client.get_user_profile.side_effect = RuntimeError("timeout")

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.health()

    assert result["status"] == "error"
    assert result["garmin"]["code"] == CONNECTION_ERROR
    assert result["garmin"]["retryable"] is True
    assert "get_user_profile failed" in result["garmin"]["message"]


def test_tool_returns_structured_error_from_client_helper() -> None:
    missing_creds = structured_error(
        MISSING_CREDENTIALS,
        "Missing Garmin credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD.",
        retryable=False,
    )

    with patch.object(server, "_get_client_or_error", return_value=(None, missing_creds)):
        result = server.get_profile()

    assert result["code"] == MISSING_CREDENTIALS
    assert result["retryable"] is False
    assert result["error"] == result["message"]
