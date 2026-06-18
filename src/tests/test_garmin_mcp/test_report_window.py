import sys
from datetime import date, timedelta
from pathlib import Path

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
