import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

GARMIN_MCP_DIR = Path(__file__).resolve().parents[3] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))

import server  # noqa: E402


def test_get_activities_includes_hr_zone_minutes() -> None:
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

    table = result["Garmin activities_past_week"]
    assert "z1" in table["Headers"]
    assert "z5" in table["Headers"]
    assert table["Rows"][0][-5:] == [10.0, 5.0, 0.0, 0.0, 0.0]


def test_get_weekly_hr_zones_aggregates_four_week_blocks() -> None:
    mock_client = MagicMock()
    today = date.today()
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 201,
            "activityType": {"typeKey": "running"},
            "startTimeLocal": f"{today.isoformat()} 07:00:00",
        }
    ]
    mock_client.get_activity_hr_in_timezones.return_value = [
        {"zoneNumber": 1, "secsInZone": 1200},
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_weekly_hr_zones()

    table = result["Garmin Weekly HR Zones"]
    assert len(table["Rows"]) == 4
    assert table["Rows"][-1][2] == 20.0


def test_weekly_report_includes_weekly_hr_zones() -> None:
    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(server, "get_weekly_mileage", return_value={"Garmin Weekly Mileage": []}),
        patch.object(server, "get_weekly_hr_zones", return_value={"Garmin Weekly HR Zones": {"Headers": [], "Rows": []}}),
        patch.object(server, "get_events", return_value={"Garmin Events": {"Headers": [], "Rows": []}}),
        patch.object(server, "get_race_predictions", return_value={"Garmin Race Predictions": {"Headers": [], "Rows": []}}),
        patch.object(server, "get_activities", return_value={"Garmin activities_past_week": {"Headers": [], "Rows": []}}),
    ):
        result = server.weekly_report()

    assert "weekly_hr_zones" in result
