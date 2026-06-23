import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

GARMIN_MCP_DIR = Path(__file__).resolve().parents[3] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))

import pytest

import server  # noqa: E402


def test_report_window_default_seven_days_ending_today() -> None:
    today = date.today()
    start_date, end_date = server._report_window(7, 0)

    assert end_date == today
    assert start_date == today - timedelta(days=6)


def test_report_window_single_day() -> None:
    today = date.today()
    start_date, end_date = server._report_window(1, 0)

    assert start_date == today
    assert end_date == today


def test_report_window_shifted_back_one_week() -> None:
    today = date.today()
    start_date, end_date = server._report_window(7, 7)

    assert end_date == today - timedelta(days=7)
    assert start_date == end_date - timedelta(days=6)


def test_report_window_rejects_non_positive_days() -> None:
    with pytest.raises(ValueError, match="days must be at least 1"):
        server._report_window(0, 0)


def test_report_window_rejects_negative_days_ago() -> None:
    with pytest.raises(ValueError, match="days_ago must be zero or positive"):
        server._report_window(7, -1)


def test_get_report_includes_training_plan_and_window() -> None:
    end_date = date.today() - timedelta(days=7)
    training_plan = [{"week_description": "current_week"}]

    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}),
        patch.object(server, "get_events", return_value={"Garmin Events": {}}),
        patch.object(server, "_training_plan_table", return_value=training_plan) as training_plan_table,
    ):
        result = server.get_report(days=7, days_ago=7)

    assert "training_plan" in result
    assert "weekly_stats" not in result
    assert result["training_plan"] == training_plan
    assert result["window"]["days"] == 7
    assert result["window"]["days_ago"] == 7
    assert result["window"]["end_date"] == end_date.isoformat()
    training_plan_table.assert_called_once()
    assert training_plan_table.call_args.kwargs["end_date"] == end_date
