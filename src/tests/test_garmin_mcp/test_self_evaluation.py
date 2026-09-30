from self_evaluation import (
    extract_self_evaluation,
    feeling_label,
    has_self_evaluation_content,
    perceived_effort,
)


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
    assert perceived_effort(0) is None
    assert perceived_effort(None) is None
    assert perceived_effort("hard") is None


def test_extract_self_evaluation_from_activity_detail() -> None:
    detail = {
        "description": "  calves tight after yesterday  ",
        "summaryDTO": {"directWorkoutFeel": 25, "directWorkoutRpe": 70},
    }
    result = extract_self_evaluation(detail=detail)
    assert result == {
        "message": "calves tight after yesterday",
        "feeling": "Weak",
        "perceived_effort": 7.0,
    }
    assert has_self_evaluation_content(result)


def test_extract_self_evaluation_falls_back_to_list_description() -> None:
    list_activity = {"description": "legs felt heavy"}
    result = extract_self_evaluation(list_activity, detail={"error": "get_activity failed"})
    assert result["message"] == "legs felt heavy"
    assert result["feeling"] is None
    assert result["perceived_effort"] is None


def test_extract_self_evaluation_empty() -> None:
    result = extract_self_evaluation({"activityName": "Run"}, detail=None)
    assert result == {"message": None, "feeling": None, "perceived_effort": None}
    assert not has_self_evaluation_content(result)
