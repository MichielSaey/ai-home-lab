from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

import rolling_week
import server


def test_anchor_end_defaults_to_yesterday() -> None:
    today = date(2026, 7, 7)
    assert rolling_week.anchor_end(0, today=today) == date(2026, 7, 6)


def test_anchor_end_shifted_by_days_ago() -> None:
    today = date(2026, 7, 7)
    assert rolling_week.anchor_end(7, today=today) == date(2026, 6, 29)


def test_block_bounds_seven_complete_days() -> None:
    anchor = date(2026, 7, 6)
    start_date, end_date = rolling_week.block_bounds(anchor)
    assert start_date == date(2026, 6, 30)
    assert end_date == anchor


def test_report_window_default_seven_days_ending_yesterday() -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)
    start_date, end_date = server._report_window(7, 0)

    assert end_date == yesterday
    assert start_date == yesterday - timedelta(days=6)


def test_report_window_single_day() -> None:
    yesterday = date.today() - timedelta(days=1)
    start_date, end_date = server._report_window(1, 0)

    assert start_date == yesterday
    assert end_date == yesterday


def test_report_window_shifted_back_one_week() -> None:
    today = date.today()
    anchor = today - timedelta(days=8)
    start_date, end_date = server._report_window(7, 7)

    assert end_date == anchor
    assert start_date == anchor - timedelta(days=6)


def test_report_window_non_seven_day_span() -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)
    start_date, end_date = server._report_window(14, 0)

    assert end_date == yesterday
    assert start_date == yesterday - timedelta(days=13)


def test_report_window_rejects_non_positive_days() -> None:
    with pytest.raises(ValueError, match="days must be at least 1"):
        server._report_window(0, 0)


def test_report_window_rejects_negative_days_ago() -> None:
    with pytest.raises(ValueError, match="days_ago must be zero or positive"):
        server._report_window(7, -1)


def test_get_report_includes_training_plan_and_window() -> None:
    anchor = date.today() - timedelta(days=8)
    training_plan = [{"week_description": "latest_week"}]

    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}),
        patch.object(server, "get_events", return_value={"Garmin Events": {}}),
        patch.object(
            server, "_training_plan_table", return_value=(training_plan, [])
        ) as training_plan_table,
    ):
        result = server.get_report(days=7, days_ago=7)

    assert "training_plan" in result
    assert "plan_weeks" not in result
    assert "weekly_stats" not in result
    assert result["training_plan"] == training_plan
    assert result["window"]["days"] == 7
    assert result["window"]["days_ago"] == 7
    assert result["window"]["end_date"] == anchor.isoformat()
    training_plan_table.assert_called_once()
    assert training_plan_table.call_args.kwargs["anchor_end"] == anchor


def test_get_report_window_matches_latest_week_block() -> None:
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = []
    mock_client.get_training_status.return_value = {}

    with (
        patch.object(server, "_get_client_or_error", return_value=(mock_client, None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(
            server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}
        ),
        patch.object(server, "get_events", return_value={"Garmin Events": {"Rows": []}}),
    ):
        result = server.get_report(days=7, days_ago=0)

    anchor = rolling_week.anchor_end(0)
    expected_start, expected_end = rolling_week.block_bounds(anchor)
    assert result["window"]["start_date"] == expected_start.isoformat()
    assert result["window"]["end_date"] == expected_end.isoformat()

    upcoming = next(
        week
        for week in result["training_plan"]
        if week["week_description"] == "upcoming_week"
    )
    assert upcoming["days"][0]["date"] == (expected_end + timedelta(days=1)).isoformat()
    assert upcoming["days"][-1]["date"] == (expected_end + timedelta(days=7)).isoformat()
