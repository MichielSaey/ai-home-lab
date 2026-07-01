import server


def test_load_coach_prompt_returns_80_20_guidance() -> None:
    prompt = server._load_coach_prompt()

    assert "80/20" in prompt
    assert "polarized" in prompt.lower()
    assert "ACWR" in prompt
    assert "week_type" in prompt
    assert "training_plan" in prompt
    assert "get_training_plan" in prompt
    assert "Taper overrides recovery" in prompt
    assert "not** open with profile" in prompt


def test_coach_prompt_prioritizes_training_plan_over_predictions() -> None:
    prompt = server._load_coach_prompt()
    plan_pos = prompt.find("get_training_plan")
    predictions_pos = prompt.find("get_race_predictions")
    assert plan_pos != -1
    assert predictions_pos != -1
    assert plan_pos < predictions_pos


def test_coach_prompt_resource_aliases_loader() -> None:
    assert server.coach_prompt() == server._load_coach_prompt()


def test_get_coach_prompt_tool_matches_resource() -> None:
    # Odysseus cannot read MCP resources, so the tool wrapper must return the
    # same content as the garmin://coach-prompt resource.
    assert server.get_coach_prompt() == server._load_coach_prompt()
    assert server.get_coach_prompt() == server.coach_prompt()
