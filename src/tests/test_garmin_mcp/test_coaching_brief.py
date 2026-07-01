from coaching_brief import build_coaching_brief


def _sample_plan() -> list[dict]:
    return [
        {
            "week_description": "past_week",
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
            "week_description": "current_week",
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
    assert "42.77" in brief["narrative"]["review_summary"]
    assert "ACWR 0.84" in brief["narrative"]["load_check"]
    assert brief["next_week_proposal"]["target_km"] == 21
    assert len(brief["next_week_proposal"]["sessions"]) == 7
    assert "medium_pct_creep" in brief["assessment"]["intensity"]["flags"]


def test_build_coaching_brief_spike_downgrades_proposal() -> None:
    plan = _sample_plan()
    plan[0]["actuals"]["acwr"] = 1.45
    brief = build_coaching_brief(plan)
    assert brief["assessment"]["acwr_label"] == "spike"
    assert brief["next_week_proposal"]["week_type"] == "recovery"


def test_build_coaching_brief_empty_plan() -> None:
    brief = build_coaching_brief([])
    assert brief.get("error") == "no_review_week"
