from coaching_brief import SESSION_TARGETS, build_coaching_brief
from training_plan import build_training_plan


def _sample_plan() -> list[dict]:
    return [
        {
            "week_description": "latest_week",
            "week_type": "build",
            "actuals": {
                "distance_km": 42.77,
                "total_zone_min": 210.0,
                "zone_1_min": 40.0,
                "zone_2_min": 140.0,
                "zone_3_min": 13.0,
                "zone_4_min": 12.0,
                "zone_5_min": 5.0,
                "easy_pct": 89.7,
                "medium_pct": 6.2,
                "hard_pct": 4.0,
                "zone_4_pct": 3.0,
                "zone_5_pct": 1.0,
                "acute_load": 473,
                "chronic_load": 564,
                "acwr": 0.84,
            },
            "target": {
                "target_min": 300,
                "easy_pct": 80,
                "medium_pct": 0,
                "zone_4_pct": 15,
                "zone_5_pct": 5,
                "hard_pct": 20,
            },
        },
        {
            "week_description": "past_week",
            "week_type": "build",
            "actuals": {"distance_km": 10.0, "total_zone_min": 50.0},
            "target": {
                "target_min": 280,
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
                "target_min": 345,
                "easy_pct": 80,
                "medium_pct": 0,
                "zone_4_pct": 15,
                "zone_5_pct": 5,
                "hard_pct": 20,
            },
            "chronic_min": 300.0,
            "outlier_weeks_dropped": [],
            "days": [
                {"date": "2026-07-07", "avg_temp_c": 18, "weather": "clear"},
                {"date": "2026-07-08", "avg_temp_c": 20, "weather": "clear"},
                {"date": "2026-07-09", "avg_temp_c": 22, "weather": "clear"},
                {"date": "2026-07-10", "avg_temp_c": 24, "weather": "clear"},
                {"date": "2026-07-11", "avg_temp_c": 26, "weather": "clear"},
                {"date": "2026-07-12", "avg_temp_c": 28, "weather": "clear"},
                {"date": "2026-07-13", "avg_temp_c": 30, "weather": "hot"},
            ],
        },
    ]


def test_build_coaching_brief_includes_narrative_and_proposal() -> None:
    brief = build_coaching_brief(_sample_plan())
    assert "narrative" in brief
    assert "latest 7 days" in brief["narrative"]["review_summary"]
    assert "210.0 min training time" in brief["narrative"]["review_summary"]
    assert "Time-based intensity" in brief["narrative"]["intensity_check"]
    assert "15% Z4" in brief["narrative"]["intensity_check"]
    assert "5% Z5" in brief["narrative"]["intensity_check"]
    assert "ACWR 0.84" in brief["narrative"]["load_check"]
    assert "personal_records_summary" in brief["narrative"]
    assert brief["presentation_order"][3] == "personal_records_summary"
    assert brief["next_week_proposal"]["target_min"] == 345
    assert "target_km" not in brief["next_week_proposal"]
    assert brief["next_week_proposal"]["chronic_min"] == 300.0
    assert isinstance(brief["next_week_proposal"]["sessions"], list)
    assert brief["next_week_proposal"]["sessions"]
    days = brief["next_week_proposal"]["days"]
    assert len(days) == 7
    assert days[0] == {"date": "2026-07-07", "avg_temp_c": 18, "weather": "clear"}
    assert days[6] == {"date": "2026-07-13", "avg_temp_c": 30, "weather": "hot"}
    flags = brief["assessment"]["intensity"]["flags"]
    assert "medium_pct_creep" in flags
    assert "under_zone_5" in flags
    assert "under_sprint" in flags
    assert "345 min" in brief["narrative"]["proposal_summary"]
    assert brief["next_week_proposal"]["session_targets"] == SESSION_TARGETS
    assert SESSION_TARGETS["threshold"]["tool"] == "create_threshold_workout"
    assert SESSION_TARGETS["threshold"]["target"] == "HR zone 4"
    assert SESSION_TARGETS["sprint"]["tool"] == "create_sprint_workout"


def test_build_coaching_brief_includes_personal_records_summary() -> None:
    prs = {
        "records": [
            {
                "label": "5K Best",
                "value": 1200,
                "display_value": "20:00",
                "activity_type": "running",
                "date": "2026-05-01",
            }
        ],
        "summary": "1 personal record(s)",
    }
    brief = build_coaching_brief(_sample_plan(), personal_records=prs)
    summary = brief["narrative"]["personal_records_summary"]
    assert "5K Best" in summary
    assert "20:00" in summary
    assert "1200" not in summary


def test_build_coaching_brief_spike_downgrades_proposal() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["acwr"] = 1.45
    brief = build_coaching_brief(plan)
    assert brief["assessment"]["acwr_label"] == "spike"
    assert brief["next_week_proposal"]["week_type"] == "recovery"
    assert brief["next_week_proposal"]["target_min"] == 240
    assert brief["upcoming_week"]["target"]["target_min"] == 240
    assert "240 min" in brief["narrative"]["proposal_summary"]


def test_build_coaching_brief_spike_uses_chronic_not_latest_km() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["acwr"] = 1.45
    plan[0]["actuals"]["distance_km"] = 20.0
    plan[0]["actuals"]["total_zone_min"] = 90.0
    plan[2]["chronic_min"] = 300.0
    brief = build_coaching_brief(plan)
    assert brief["next_week_proposal"]["target_min"] == 240


def test_build_coaching_brief_passes_recent_activities_without_day_prescriptions() -> None:
    plan = _sample_plan()
    recent = [
        {
            "date": "2026-07-07",
            "name": "Recovery Run",
            "activity_type": "running",
            "distance_km": 8.0,
            "duration_min": 50,
            "training_effect": "Recovery",
        },
        {
            "date": "2026-07-08",
            "name": "Z2 Ride",
            "activity_type": "cycling",
            "distance_km": 25.0,
            "duration_min": 60,
            "training_effect": "Base",
        },
    ]
    brief = build_coaching_brief(plan, recent_activities=recent)
    assert brief["recent_activities"] == recent
    assert "Z2 Ride" in brief["narrative"]["load_check"]
    assert "60 min" in brief["narrative"]["load_check"]
    days = brief["next_week_proposal"]["days"]
    assert all("session" not in day for day in days)
    assert all("workout_type" not in day for day in days)


def test_build_coaching_brief_proposal_days_without_weather() -> None:
    stat_rows = [
        [
            "2026-05-26",
            "2026-06-01",
            40.0,
            250,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            80.0,
            0.0,
            20.0,
            15.0,
            5.0,
        ],
    ]
    plan = build_training_plan(
        stat_rows, event_date=None, load_at_week_end=lambda _e: {}
    )
    brief = build_coaching_brief(plan)
    days = brief["next_week_proposal"]["days"]
    assert len(days) == 7
    assert days[0]["date"] == "2026-06-02"
    assert days[0]["avg_temp_c"] is None
    assert brief["next_week_proposal"]["target_min"] == 288


def test_build_coaching_brief_empty_plan() -> None:
    brief = build_coaching_brief([])
    assert brief.get("error") == "no_review_week"


def test_build_coaching_brief_nudge_for_under_sprint() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["medium_pct"] = 0.0
    plan[0]["actuals"]["zone_3_min"] = 0.0
    plan[0]["actuals"]["easy_pct"] = 96.0
    plan[0]["actuals"]["hard_pct"] = 4.0
    plan[0]["actuals"]["zone_4_pct"] = 3.0
    plan[0]["actuals"]["zone_5_pct"] = 1.0
    brief = build_coaching_brief(plan)
    assert "under_sprint" in brief["assessment"]["intensity"]["flags"]
    assert "Z5" in brief["next_week_proposal"]["focus"]


def test_time_intensity_overview_treats_zero_as_unavailable() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["total_zone_min"] = 0.0
    plan[0]["actuals"]["zone_1_min"] = 0.0
    plan[0]["actuals"]["zone_2_min"] = 0.0
    plan[0]["actuals"]["zone_3_min"] = 0.0
    plan[0]["actuals"]["zone_4_min"] = 0.0
    plan[0]["actuals"]["zone_5_min"] = 0.0
    brief = build_coaching_brief(plan)
    assert "unavailable" in brief["narrative"]["intensity_check"]
    assert "0 min total" not in brief["narrative"]["intensity_check"]


def test_spike_deload_with_zero_run_distance_uses_chronic() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["acwr"] = 1.45
    plan[0]["actuals"]["distance_km"] = 0.0
    plan[0]["actuals"]["total_zone_min"] = 180.0
    plan[2]["chronic_min"] = 300.0
    brief = build_coaching_brief(plan)
    assert brief["assessment"]["acwr_label"] == "spike"
    assert brief["next_week_proposal"]["week_type"] == "recovery"
    assert brief["next_week_proposal"]["target_min"] == 240


def test_build_coaching_brief_volume_uses_minutes() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["distance_km"] = 0.0
    plan[0]["actuals"]["total_zone_min"] = 180.0
    plan[0]["actuals"]["medium_pct"] = 0.0
    plan[0]["actuals"]["zone_3_min"] = 0.0
    plan[0]["actuals"]["easy_pct"] = 80.0
    plan[0]["actuals"]["hard_pct"] = 20.0
    plan[0]["actuals"]["zone_4_pct"] = 15.0
    plan[0]["actuals"]["zone_5_pct"] = 5.0
    brief = build_coaching_brief(plan)
    summary = brief["narrative"]["review_summary"]
    assert "180.0 min training time" in summary
    assert "0 km" not in summary
    assert "below the plan target of 300 min" in summary
    assert brief["assessment"]["volume"]["vs_target"] == "below_target"
    assert brief["assessment"]["volume"]["target_min"] == 300
