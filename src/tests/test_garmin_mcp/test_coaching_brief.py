from coaching_brief import build_coaching_brief
from training_plan import build_training_plan


def _sample_plan() -> list[dict]:
    return [
        {
            "week_description": "latest_week",
            "week_type": "build",
            "actuals": {
                "distance_km": 42.77,
                "easy_pct": 89.7,
                "medium_pct": 6.2,
                "hard_pct": 4.0,
                "acute_load": 473,
                "chronic_load": 564,
                "acwr": 0.84,
            },
            "target": {
                "distance_km": 27,
                "easy_pct": 80,
                "medium_pct": 0,
                "hard_pct": 20,
            },
        },
        {
            "week_description": "past_week",
            "week_type": "build",
            "actuals": {"distance_km": 10.0},
            "target": {"distance_km": 30, "easy_pct": 80, "medium_pct": 0, "hard_pct": 20},
        },
        {
            "week_description": "upcoming_week",
            "week_type": "build",
            "actuals": {},
            "target": {"distance_km": 21, "easy_pct": 80, "medium_pct": 0, "hard_pct": 20},
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
    assert "ACWR 0.84" in brief["narrative"]["load_check"]
    assert brief["next_week_proposal"]["target_km"] == 21
    assert "sessions" not in brief["next_week_proposal"]
    days = brief["next_week_proposal"]["days"]
    assert len(days) == 7
    assert days[0] == {"date": "2026-07-07", "avg_temp_c": 18, "weather": "clear"}
    assert days[6] == {"date": "2026-07-13", "avg_temp_c": 30, "weather": "hot"}
    assert "medium_pct_creep" in brief["assessment"]["intensity"]["flags"]


def test_build_coaching_brief_spike_downgrades_proposal() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["acwr"] = 1.45
    brief = build_coaching_brief(plan)
    assert brief["assessment"]["acwr_label"] == "spike"
    assert brief["next_week_proposal"]["week_type"] == "recovery"
    assert brief["next_week_proposal"]["target_km"] == 34
    assert brief["upcoming_week"]["target"]["distance_km"] == 34
    assert "34 km" in brief["narrative"]["proposal_summary"]


def test_build_coaching_brief_passes_recent_activities_without_prescriptions() -> None:
    plan = _sample_plan()
    recent = [
        {
            "date": "2026-07-07",
            "name": "Recovery Run",
            "distance_km": 8.0,
            "training_effect": "Recovery",
        },
        {
            "date": "2026-07-08",
            "name": "Easy Run",
            "distance_km": 6.0,
            "training_effect": "Base",
        },
    ]
    brief = build_coaching_brief(plan, recent_activities=recent)
    assert brief["recent_activities"] == recent
    days = brief["next_week_proposal"]["days"]
    assert all("session" not in day for day in days)
    assert all("workout_type" not in day for day in days)
    assert all("duration_min" not in day for day in days)


def test_build_coaching_brief_proposal_days_without_weather() -> None:
    stat_rows = [
        ["2026-05-26", "2026-06-01", 40.0, 0, 0, 0, 0, 0, 0, 0, 0, 80.0, 0.0, 20.0],
    ]
    plan = build_training_plan(
        stat_rows, event_date=None, load_at_week_end=lambda _e: {}
    )
    brief = build_coaching_brief(plan)
    days = brief["next_week_proposal"]["days"]
    assert len(days) == 7
    assert days[0]["date"] == "2026-06-02"
    assert days[0]["avg_temp_c"] is None


def test_build_coaching_brief_empty_plan() -> None:
    brief = build_coaching_brief([])
    assert brief.get("error") == "no_review_week"
