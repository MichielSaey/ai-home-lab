from datetime import date, timedelta
from unittest.mock import ANY, MagicMock, patch

import server


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

    yesterday = date.today() - timedelta(days=1)
    week_start = yesterday - timedelta(days=6)
    mock_client.get_activities_by_date.assert_called_once_with(
        week_start.isoformat(),
        yesterday.isoformat(),
    )
    assert result["window"]["end_date"] == yesterday.isoformat()

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
    yesterday = date.today() - timedelta(days=1)
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 201,
            "activityType": {"typeKey": "running"},
            "distance": 10000,
            "startTimeLocal": f"{yesterday.isoformat()} 07:00:00",
        }
    ]
    mock_client.get_activity_hr_in_timezones.return_value = [
        {"zoneNumber": 1, "secsInZone": 1200},
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_weekly_stats()

    table = result["Garmin Weekly Stats"]
    assert table["Headers"][2] == "distance_km"
    assert table["Headers"][3] == "total_zone_min"
    assert table["Headers"][4] == "zone_1_min"
    assert table["Headers"][-2:] == ["zone_4_pct", "zone_5_pct"]
    assert len(table["Rows"]) == 4
    current_week = table["Rows"][-1]
    assert current_week[2] == 10.0
    assert current_week[3] == 20.0  # total_zone_min
    assert current_week[4] == 20.0  # zone_1_min


def test_get_activities_handles_null_activity_type() -> None:
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 501,
            "activityName": "Mystery",
            "activityType": None,
            "distance": 1000,
            "movingDuration": 600,
            "averageSpeed": None,
            "maxSpeed": None,
            "maxHR": 120,
            "averageHR": 100,
            "aerobicTrainingEffect": 1.0,
            "anaerobicTrainingEffect": 0.0,
            "trainingEffectLabel": "Recovery",
            "startTimeLocal": "2026-06-16 07:00:00",
        }
    ]
    mock_client.get_activity_hr_in_timezones.return_value = []

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_activities(days_back=7)

    assert len(result["Garmin Activities"]["Rows"]) == 1
    assert result["Garmin Activities"]["Rows"][0][1] is None


def test_get_activities_includes_non_running_types() -> None:
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 301,
            "activityName": "Morning Ride",
            "activityType": {"typeKey": "cycling"},
            "distance": 25000,
            "movingDuration": 3600,
            "averageSpeed": 6.9,
            "maxSpeed": 10.0,
            "maxHR": 160,
            "averageHR": 140,
            "aerobicTrainingEffect": 3.0,
            "anaerobicTrainingEffect": 0.2,
            "trainingEffectLabel": "Tempo",
            "startTimeLocal": "2026-06-16 07:00:00",
        },
        {
            "activityId": 302,
            "activityName": "Gym",
            "activityType": {"typeKey": "strength_training"},
            "distance": 0,
            "movingDuration": 2700,
            "averageSpeed": None,
            "maxSpeed": None,
            "maxHR": 130,
            "averageHR": 110,
            "aerobicTrainingEffect": 1.0,
            "anaerobicTrainingEffect": 2.0,
            "trainingEffectLabel": "Strength",
            "startTimeLocal": "2026-06-15 18:00:00",
        },
    ]
    mock_client.get_activity_hr_in_timezones.return_value = [
        {"zoneNumber": 2, "secsInZone": 1800},
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_activities(days_back=7)

    rows = result["Garmin Activities"]["Rows"]
    assert len(rows) == 2
    types = {row[1] for row in rows}
    assert types == {"cycling", "strength_training"}


def test_get_weekly_stats_includes_non_running_types() -> None:
    mock_client = MagicMock()
    yesterday = date.today() - timedelta(days=1)
    mock_client.get_activities_by_date.return_value = [
        {
            "activityId": 401,
            "activityType": {"typeKey": "cycling"},
            "distance": 30000,
            "startTimeLocal": f"{yesterday.isoformat()} 07:00:00",
        },
        {
            "activityId": 402,
            "activityType": {"typeKey": "strength_training"},
            "distance": 0,
            "startTimeLocal": f"{yesterday.isoformat()} 18:00:00",
        },
    ]

    def _zones(activity_id: str):
        if str(activity_id) == "401":
            return [{"zoneNumber": 2, "secsInZone": 2400}]
        return [{"zoneNumber": 1, "secsInZone": 1200}]

    mock_client.get_activity_hr_in_timezones.side_effect = _zones

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_weekly_stats(weeks=1)

    current_week = result["Garmin Weekly Stats"]["Rows"][-1]
    # Non-run distance excluded from km volume; zones still roll up from all sports
    assert current_week[2] == 0.0
    assert current_week[3] == 60.0  # 40 + 20 zone minutes


def test_get_personal_records_normalizes_list() -> None:
    mock_client = MagicMock()
    mock_client.get_personal_record.return_value = [
        {
            "typeId": 1,  # 1K — excluded from coaching card
            "activityName": "Track Running",
            "value": 201,
            "activityType": {"typeKey": "running"},
            "prStartTimeGMT": "2026-05-02T10:00:00.000Z",
        },
        {
            "typeId": 3,
            "activityName": "Track Running",
            "value": 1200,
            "activityType": {"typeKey": "running"},
            "prStartTimeGMT": "2026-05-01T10:00:00.000Z",
        },
        {
            "typeId": 7,
            "activityName": "Long Sunday",
            "value": 32100,
            "activityType": {"typeKey": "running"},
            "prStartTimeGMT": "2026-04-01T08:00:00.000Z",
        },
        {
            "typeId": 12,  # steps — excluded
            "activityName": "Steps",
            "value": 25000,
            "activityType": {"typeKey": "walking"},
        },
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_personal_records()

    assert result["summary"] == "2 personal record(s)"
    labels = [row["label"] for row in result["records"]]
    assert labels == ["5K", "Longest Run"]
    assert result["records"][0]["value"] == 1200
    assert result["records"][0]["display_value"] == "20:00"
    assert result["records"][0]["activity_type"] == "running"
    assert result["records"][0]["date"] == "2026-05-01"
    assert result["records"][1]["display_value"] == "32.10 km"


def test_get_personal_records_keeps_race_ladder_and_longest() -> None:
    mock_client = MagicMock()
    mock_client.get_personal_record.return_value = [
        {"typeId": 7, "value": 40000, "activityType": "running"},
        {"typeId": 6, "value": 11186, "activityType": "running"},
        {"typeId": 4, "value": 2400, "activityType": "running"},
        {"typeId": 5, "value": 5301, "activityType": "running"},
        {"typeId": 2, "value": 360, "activityType": "running"},  # mile excluded
        {"typeId": 3, "value": 1200, "activityType": "running"},
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_personal_records()

    assert [row["label"] for row in result["records"]] == [
        "5K",
        "10K",
        "Half Marathon",
        "Marathon",
        "Longest Run",
    ]
    assert result["records"][-1]["display_value"] == "40.00 km"


def test_get_personal_records_label_only_15k_sorts_before_longest() -> None:
    mock_client = MagicMock()
    mock_client.get_personal_record.return_value = [
        {"typeId": 7, "value": 40000, "activityType": "running"},
        {"prType": "15K Best", "value": 3600, "activityType": "running"},
        {"typeId": 4, "value": 2400, "activityType": "running"},
        {"activityName": "Longest Ride", "value": 90000},  # excluded
        {"prType": "25K Best", "value": 7200, "activityType": "running"},  # excluded
    ]

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_personal_records()

    assert [row["label"] for row in result["records"]] == [
        "10K",
        "15K Best",
        "Longest Run",
    ]


def test_get_personal_records_handles_unexpected_shape() -> None:
    mock_client = MagicMock()
    mock_client.get_personal_record.return_value = "not-a-payload"

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_personal_records()

    assert result["records"] == []
    assert "raw" in result


def test_get_coaching_brief_includes_personal_records() -> None:
    prs = {
        "records": [
            {
                "label": "5K Best",
                "value": 1200,
                "activity_type": "running",
                "date": "2026-05-01",
            }
        ],
        "summary": "1 personal record(s)",
    }
    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}),
        patch.object(server, "get_personal_records", return_value=prs),
        patch.object(server, "get_events", return_value={"Garmin Events": {}, "latest_event": None}),
        patch.object(
            server,
            "_training_plan_table",
            return_value=(
                [
                    {
                        "week_description": "latest_week",
                        "week_type": "build",
                        "actuals": {
                            "distance_km": 40,
                            "total_zone_min": 100,
                            "easy_pct": 80,
                            "medium_pct": 0,
                            "hard_pct": 20,
                            "zone_4_pct": 15,
                            "zone_5_pct": 5,
                            "acwr": 1.0,
                        },
                        "target": {
                            "distance_km": 40,
                            "easy_pct": 80,
                            "medium_pct": 0,
                            "zone_4_pct": 15,
                            "zone_5_pct": 5,
                            "hard_pct": 20,
                        },
                    },
                    {
                        "week_description": "upcoming_week",
                        "week_type": "build",
                        "actuals": {},
                        "target": {
                            "distance_km": 44,
                            "easy_pct": 80,
                            "medium_pct": 0,
                            "zone_4_pct": 15,
                            "zone_5_pct": 5,
                            "hard_pct": 20,
                        },
                        "days": [],
                    },
                ],
                [],
            ),
        ),
        patch.object(server, "_activities_table") as activities_table,
    ):
        result = server.get_coaching_brief()

    assert result["personal_records"] == prs
    assert "5K Best" in result["coaching_brief"]["narrative"]["personal_records_summary"]
    activities_table.assert_not_called()


def test_get_coaching_brief_soft_fails_coded_personal_record_errors() -> None:
    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}),
        patch.object(
            server,
            "get_personal_records",
            return_value={"error": "PR endpoint failed", "code": "garmin_api_error"},
        ),
        patch.object(server, "get_events", return_value={"Garmin Events": {}, "latest_event": None}),
        patch.object(
            server,
            "_training_plan_table",
            return_value=(
                [
                    {
                        "week_description": "latest_week",
                        "week_type": "build",
                        "actuals": {
                            "distance_km": 40,
                            "total_zone_min": 100,
                            "easy_pct": 80,
                            "medium_pct": 0,
                            "hard_pct": 20,
                            "zone_4_pct": 15,
                            "zone_5_pct": 5,
                            "acwr": 1.0,
                        },
                        "target": {
                            "distance_km": 40,
                            "easy_pct": 80,
                            "medium_pct": 0,
                            "zone_4_pct": 15,
                            "zone_5_pct": 5,
                            "hard_pct": 20,
                        },
                    },
                    {
                        "week_description": "upcoming_week",
                        "week_type": "build",
                        "actuals": {},
                        "target": {
                            "distance_km": 44,
                            "easy_pct": 80,
                            "medium_pct": 0,
                            "zone_4_pct": 15,
                            "zone_5_pct": 5,
                            "hard_pct": 20,
                        },
                        "days": [],
                    },
                ],
                [],
            ),
        ),
    ):
        result = server.get_coaching_brief()

    assert "coaching_brief" in result
    assert result["personal_records"]["records"] == []
    assert "PR endpoint failed" in result["personal_records"]["summary"]


def test_get_coaching_brief_is_primary_coach_bundle() -> None:
    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}),
        patch.object(
            server,
            "get_personal_records",
            return_value={"records": [], "summary": "No personal records"},
        ),
        patch.object(server, "get_events", return_value={"Garmin Events": {}, "latest_event": None}),
        patch.object(
            server,
            "_training_plan_table",
            return_value=([{"week_description": "upcoming_week"}], []),
        ),
        patch.object(server, "_activities_table") as activities_table,
    ):
        result = server.get_coaching_brief()

    assert "training_plan" in result
    assert "coaching_brief" in result
    assert "personal_records" in result
    assert "plan_weeks" not in result
    assert "activities" not in result
    activities_table.assert_not_called()


def test_get_coaching_brief_can_include_activities() -> None:
    with (
        patch.object(server, "_get_client_or_error", return_value=(MagicMock(), None)),
        patch.object(server, "get_profile", return_value={}),
        patch.object(server, "get_race_predictions", return_value={}),
        patch.object(
            server,
            "get_personal_records",
            return_value={"records": [], "summary": "No personal records"},
        ),
        patch.object(server, "get_events", return_value={}),
        patch.object(server, "_training_plan_table", return_value=([], [])),
        patch.object(server, "_activities_table", return_value={"Garmin Activities": {}}) as activities_table,
    ):
        result = server.get_coaching_brief(include_activities=True)

    assert "activities" in result
    activities_table.assert_called_once_with(
        ANY,
        days=7,
        days_ago=0,
        include_hr_zones=True,
    )


def test_recent_activity_summaries_include_activity_id() -> None:
    summaries = server._recent_activity_summaries(
        [
            {
                "activityId": 101,
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "distance": 5000,
                "movingDuration": 1800,
                "trainingEffectLabel": "Base",
                "averageHR": 140,
                "startTimeLocal": "2026-09-28 07:00:00",
            }
        ]
    )
    assert summaries[0]["activity_id"] == 101
    assert "self_evaluation" not in summaries[0]


def test_enrich_self_evaluations_this_week_only() -> None:
    mock_client = MagicMock()
    mock_client.get_activity.side_effect = lambda aid: {
        "description": f"note {aid}",
        "summaryDTO": {"directWorkoutFeel": 75, "directWorkoutRpe": 60},
    }
    summaries = [
        {"date": "2026-09-28", "activity_id": 1, "name": "Run"},
        {"date": "2026-09-20", "activity_id": 2, "name": "Old"},
    ]
    activities = [
        {"activityId": 1, "description": "list note"},
        {"activityId": 2},
    ]

    server._enrich_self_evaluations(
        mock_client,
        summaries,
        activities,
        date(2026, 9, 24),
        date(2026, 9, 30),
    )

    assert summaries[0]["self_evaluation"] == "note 1"
    assert summaries[0]["feeling"] == "Strong"
    assert summaries[0]["perceived_effort"] == 6.0
    assert "self_evaluation" not in summaries[1]
    assert "feeling" not in summaries[1]
    mock_client.get_activity.assert_called_once_with("1")


def test_enrich_self_evaluations_falls_back_to_list_description() -> None:
    mock_client = MagicMock()
    mock_client.get_activity.side_effect = RuntimeError("garmin down")
    summaries = [{"date": "2026-09-28", "activity_id": 1, "name": "Run"}]
    activities = [{"activityId": 1, "description": "calves tight"}]

    server._enrich_self_evaluations(
        mock_client,
        summaries,
        activities,
        date(2026, 9, 24),
        date(2026, 9, 30),
    )

    assert summaries[0]["self_evaluation"] == "calves tight"
    assert summaries[0]["feeling"] is None


def test_get_report_attaches_self_evaluation_for_latest_week() -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)
    older = yesterday - timedelta(days=10)
    mock_client = MagicMock()
    mock_client.get_activity.return_value = {
        "description": "felt strong on the last k",
        "summaryDTO": {"directWorkoutFeel": 100, "directWorkoutRpe": 50},
    }
    this_week = {
        "activityId": 11,
        "activityName": "Threshold",
        "activityType": {"typeKey": "running"},
        "distance": 8000,
        "movingDuration": 2400,
        "trainingEffectLabel": "Tempo",
        "averageHR": 160,
        "startTimeLocal": f"{yesterday.isoformat()} 07:00:00",
        "description": "list leftover",
    }
    last_month = {
        "activityId": 99,
        "activityName": "Old Long",
        "activityType": {"typeKey": "running"},
        "distance": 20000,
        "movingDuration": 7200,
        "trainingEffectLabel": "Base",
        "averageHR": 145,
        "startTimeLocal": f"{older.isoformat()} 08:00:00",
    }
    training_plan = [
        {
            "week_description": "latest_week",
            "week_type": "build",
            "actuals": {
                "distance_km": 8,
                "total_zone_min": 40,
                "easy_pct": 80,
                "medium_pct": 0,
                "hard_pct": 20,
                "zone_4_pct": 15,
                "zone_5_pct": 5,
                "acwr": 1.0,
            },
            "target": {
                "target_min": 40,
                "easy_pct": 80,
                "medium_pct": 0,
                "zone_4_pct": 15,
                "zone_5_pct": 5,
                "hard_pct": 20,
            },
        },
        {
            "week_description": "upcoming_week",
            "week_type": "build",
            "actuals": {},
            "target": {"target_min": 44},
            "days": [],
        },
    ]

    with (
        patch.object(server, "_get_client_or_error", return_value=(mock_client, None)),
        patch.object(server, "get_profile", return_value={"weight": 70}),
        patch.object(
            server, "get_race_predictions", return_value={"Garmin Race Predictions": {}}
        ),
        patch.object(
            server,
            "get_personal_records",
            return_value={"records": [], "summary": "No personal records"},
        ),
        patch.object(
            server, "get_events", return_value={"Garmin Events": {}, "latest_event": None}
        ),
        patch.object(
            server,
            "_training_plan_table",
            return_value=(training_plan, [this_week, last_month]),
        ),
    ):
        # days=14 widens the report window; notes still attach only to latest_week.
        result = server.get_report(days=14, days_ago=0)

    recent = result["coaching_brief"]["recent_activities"]
    by_name = {row["name"]: row for row in recent}
    assert by_name["Threshold"]["self_evaluation"] == "felt strong on the last k"
    assert by_name["Threshold"]["feeling"] == "Very Strong"
    assert by_name["Threshold"]["perceived_effort"] == 5.0
    assert "self_evaluation" not in by_name["Old Long"]
    assert "felt strong on the last k" in result["coaching_brief"]["narrative"][
        "self_evaluation_notes"
    ]
    mock_client.get_activity.assert_called_once_with("11")


def test_weekly_report_resource_aliases_get_report() -> None:
    with patch.object(
        server, "get_report", return_value={"profile": {}, "training_plan": []}
    ) as get_report:
        result = server.weekly_report()

    assert result == {"profile": {}, "training_plan": []}
    get_report.assert_called_once_with(days=7, days_ago=0)


def test_weekly_report_resource_for_days_clamps_and_forwards() -> None:
    with patch.object(
        server, "get_report", return_value={"profile": {}}
    ) as get_report:
        server.weekly_report_for_days(120)

    get_report.assert_called_once_with(days=90, days_ago=0)


def test_get_profile_handles_missing_user_profile() -> None:
    mock_client = MagicMock()
    del mock_client.get_user_profile

    with patch.object(server, "_get_client_or_error", return_value=(mock_client, None)):
        result = server.get_profile()

    assert result["error"] == "No profile returned from Garmin"
