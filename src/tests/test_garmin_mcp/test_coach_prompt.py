import server


def test_load_coach_prompt_returns_80_20_guidance() -> None:
    prompt = server._load_coach_prompt()

    assert "80/20" in prompt
    assert "polarized" in prompt.lower()
    assert "ACWR" in prompt
    assert "week_type" in prompt
    assert "training_plan" in prompt
    assert "Taper overrides recovery" in prompt


def test_coach_prompt_resource_aliases_loader() -> None:
    assert server.coach_prompt() == server._load_coach_prompt()
