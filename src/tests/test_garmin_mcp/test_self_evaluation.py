from self_evaluation import extract_self_evaluation, feeling_label, perceived_effort


def test_feeling_label_maps_garmin_scores() -> None:
    assert feeling_label(0) == "Very Weak"
    assert feeling_label(25) == "Weak"
    assert feeling_label(50) == "Normal"
    assert feeling_label(75) == "Strong"
    assert feeling_label(100) == "Very Strong"
    assert feeling_label(70) == "Strong"
    assert feeling_label(None) is None
    assert feeling_label("nope") is None


def test_perceived_effort_normalizes_0_100_and_1_10() -> None:
    assert perceived_effort(60) == 6.0
    assert perceived_effort(6) == 6.0
    assert perceived_effort(10) == 1.0
    assert perceived_effort(100) == 10.0
    assert perceived_effort(0) is None
    assert perceived_effort(None) is None
    assert perceived_effort("hard") is None


def test_extract_self_evaluation_note_is_free_text() -> None:
    detail = {
        "description": "  low on energy after a bad night  ",
        "summaryDTO": {"directWorkoutFeel": 25, "directWorkoutRpe": 70},
    }
    result = extract_self_evaluation(detail=detail)
    assert result["self_evaluation"] == "low on energy after a bad night"
    assert isinstance(result["self_evaluation"], str)
    assert result["feeling"] == "Weak"
    assert result["perceived_effort"] == 7.0


def test_extract_self_evaluation_falls_back_to_list_description() -> None:
    list_activity = {"description": "legs felt heavy"}
    result = extract_self_evaluation(list_activity, detail={"error": "get_activity failed"})
    assert result["self_evaluation"] == "legs felt heavy"
    assert result["feeling"] is None
    assert result["perceived_effort"] is None


def test_extract_self_evaluation_uses_comments_when_description_missing() -> None:
    result = extract_self_evaluation({"comments": "niggle in the left calf"})
    assert result["self_evaluation"] == "niggle in the left calf"


def test_extract_self_evaluation_empty_note_keeps_scores() -> None:
    result = extract_self_evaluation(
        {"activityName": "Run"},
        detail={"summaryDTO": {"directWorkoutFeel": 75, "directWorkoutRpe": 50}},
    )
    assert result["self_evaluation"] is None
    assert result["feeling"] == "Strong"
    assert result["perceived_effort"] == 5.0


def test_extract_self_evaluation_empty() -> None:
    result = extract_self_evaluation({"activityName": "Run"}, detail=None)
    assert result == {
        "self_evaluation": None,
        "feeling": None,
        "perceived_effort": None,
    }
