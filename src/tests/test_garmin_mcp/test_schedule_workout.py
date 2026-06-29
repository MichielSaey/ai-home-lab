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


def test_schedule_workout_rejects_non_iso_date() -> None:
    mock_client = MagicMock()

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.schedule_workout(42, "June 20")

    assert "error" in result
    mock_client.schedule_workout.assert_not_called()


def test_create_template_with_workout_date_also_schedules() -> None:
    mock_client = MagicMock()
    mock_client.get_scheduled_workouts.return_value = {"calendarItems": []}
    mock_client.schedule_workout.return_value = {"workoutScheduleId": 9100}

    with (
        patch.object(server, "_get_client_or_error", return_value=(mock_client, None)),
        patch.object(server, "_upload_running_workout", return_value={"workoutId": 555}),
        patch.object(server, "get_profile", return_value={}),
        patch.object(server, "resolve_hr_context", return_value={"zones": []}),
    ):
        result = server.create_base_workout(duration_minutes=30, workout_date="2026-07-01")

    assert result["workoutId"] == 555
    assert result["schedule"]["schedule"] == {"workoutScheduleId": 9100}
    mock_client.schedule_workout.assert_called_once_with(555, "2026-07-01")


def test_create_template_without_workout_date_does_not_schedule() -> None:
    mock_client = MagicMock()

    with (
        patch.object(server, "_get_client_or_error", return_value=(mock_client, None)),
        patch.object(server, "_upload_running_workout", return_value={"workoutId": 555}),
        patch.object(server, "get_profile", return_value={}),
        patch.object(server, "resolve_hr_context", return_value={"zones": []}),
    ):
        result = server.create_base_workout(duration_minutes=30)

    assert "schedule" not in result
    mock_client.schedule_workout.assert_not_called()


def test_create_template_with_bad_workout_date_returns_error_before_upload() -> None:
    mock_client = MagicMock()

    with (
        patch.object(server, "_get_client_or_error", return_value=(mock_client, None)),
        patch.object(server, "_upload_running_workout") as mock_upload,
    ):
        result = server.create_base_workout(duration_minutes=30, workout_date="not-a-date")

    assert "error" in result
    mock_upload.assert_not_called()
