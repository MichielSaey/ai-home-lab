import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

GARMIN_MCP_DIR = Path(__file__).resolve().parents[3] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))

import server  # noqa: E402


def test_get_activities_uses_readable_headers_and_zone_minutes() -> None:
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 101,
            "activityName": "Morning Run",
            "activityType": {"typeKey": "running"},
            "distance": 5000,
            "movingDuration": 1800,
            "averageSpeed": 2.5,
            "maxSpeed": 3.0,
            "maxHR": 165,
            "averageHR": 145,
            "aerobicTrainingEffect": 2.5,
            "anaerobicTrainingEffect": 0.1,
            "trainingEffectLabel": "Aerobic Base",
            "startTimeLocal": "2026-06-16 07:00:00",
        }
    ]
    mock_client.get_activity_hr_in_timezones.return_value = [
        {"zoneNumber": 1, "secsInZone": 600},
        {"zoneNumber": 2, "secsInZone": 300},
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_activities(days_back=7)

    table = result["Garmin Activities"]
    assert table["Headers"][0] == "name"
    assert table["Headers"][-1] == "zone_5_min"
    assert table["Rows"][0][-5:] == [10.0, 5.0, 0.0, 0.0, 0.0]


def test_get_activities_can_skip_hr_zones() -> None:
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 101,
            "activityName": "Morning Run",
            "activityType": {"typeKey": "running"},
            "distance": 5000,
            "movingDuration": 1800,
            "averageSpeed": 2.5,
            "maxSpeed": 3.0,
            "maxHR": 165,
            "averageHR": 145,
            "aerobicTrainingEffect": 2.5,
            "anaerobicTrainingEffect": 0.1,
            "trainingEffectLabel": "Aerobic Base",
            "startTimeLocal": "2026-06-16 07:00:00",
        }
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_activities(days_back=7, include_hr_zones=False)

    table = result["Garmin Activities"]
    assert "zone_1_min" not in table["Headers"]
    assert len(table["Rows"][0]) == 11
    mock_client.get_activity_hr_in_timezones.assert_not_called()


def test_get_weekly_stats_combines_distance_and_zones() -> None:
    mock_client = MagicMock()
    today = date.today()
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 201,
            "activityType": {"typeKey": "running"},
            "distance": 10000,
            "startTimeLocal": f"{today.isoformat()} 07:00:00",
        }
    ]
    mock_client.get_activity_hr_in_timezones.return_value = [
        {"zoneNumber": 1, "secsInZone": 1200},
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_weekly_stats()

    table = result["Garmin Weekly Stats"]
    assert table["Headers"][2] == "distance_km"
    assert table["Headers"][3] == "zone_1_min"
    assert len(table["Rows"]) == 4
    current_week = table["Rows"][-1]
    assert current_week[2] == 10.0
    assert current_week[3] == 20.0


def test_get_weekly_report_is_tool_without_activities_by_default() -> None:
    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}),
        patch.object(server, "get_events", return_value={"Garmin Events": {}}),
        patch.object(
            server,
            "_weekly_stats_table",
            return_value={"Garmin Weekly Stats": {"Headers": [], "Rows": []}},
        ),
        patch.object(server, "_activities_table") as activities_table,
    ):
        result = server.get_weekly_report()

    assert "weekly_stats" in result
    assert "activities" not in result
    activities_table.assert_not_called()


def test_weekly_report_resource_aliases_get_weekly_report() -> None:
    with patch.object(
        server, "get_weekly_report", return_value={"profile": {}, "weekly_stats": {}}
    ) as get_weekly_report:
        result = server.weekly_report()

    assert result == {"profile": {}, "weekly_stats": {}}
    get_weekly_report.assert_called_once_with()


def test_weekly_report_resource_for_days_clamps_and_forwards() -> None:
    with patch.object(
        server, "get_weekly_report", return_value={"profile": {}}
    ) as get_weekly_report:
        server.weekly_report_for_days(120)

    get_weekly_report.assert_called_once_with(days_back=90)


def test_get_profile_handles_missing_user_profile() -> None:
    mock_client = MagicMock()
    del mock_client.get_user_profile

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_profile()

    assert result["weight"] == 0.0
    assert result["availableTrainingDays"] == []


def test_get_weekly_report_can_include_activities() -> None:
    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={}),
        patch.object(server, "get_race_predictions", return_value={}),
        patch.object(server, "get_events", return_value={}),
        patch.object(server, "_weekly_stats_table", return_value={}),
        patch.object(server, "_activities_table", return_value={"Garmin Activities": {}}) as activities_table,
    ):
        result = server.get_weekly_report(include_activities=True)

    assert "activities" in result
    activities_table.assert_called_once()
