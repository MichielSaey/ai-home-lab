from unittest.mock import MagicMock, patch

import server


def test_schedule_workout_skips_duplicate_calendar_entry() -> None:
    mock_client = MagicMock()
    mock_client.get_scheduled_workouts.return_value = {
        "calendarItems": [
            {
                "itemType": "workout",
                "date": "2026-06-20",
                "workoutId": 42,
            }
        ]
    }

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.schedule_workout(42, "2026-06-20")

    assert result["alreadyScheduled"] is True
    assert result["workoutId"] == 42
    assert result["date"] == "2026-06-20"
    mock_client.schedule_workout.assert_not_called()


def test_schedule_workout_calls_garmin_when_not_already_scheduled() -> None:
    mock_client = MagicMock()
    mock_client.get_scheduled_workouts.return_value = {"calendarItems": []}
    mock_client.schedule_workout.return_value = {"workoutScheduleId": 9001}

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.schedule_workout(42, "2026-06-20")

    assert "alreadyScheduled" not in result
    assert result["schedule"] == {"workoutScheduleId": 9001}
    mock_client.schedule_workout.assert_called_once_with(42, "2026-06-20")


def test_schedule_workout_matches_nested_workout_payload() -> None:
    mock_client = MagicMock()
    mock_client.get_scheduled_workouts.return_value = {
        "calendarItems": [
            {
                "itemType": "workout",
                "calendarDate": "2026-06-20",
                "workout": {"workoutId": 77},
            }
        ]
    }

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.schedule_workout(77, "2026-06-20")

    assert result["alreadyScheduled"] is True
    mock_client.schedule_workout.assert_not_called()
