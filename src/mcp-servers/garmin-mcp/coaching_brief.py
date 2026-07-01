"""Deterministic coaching brief — review, assessment, and next-week proposal.

Computed server-side so the LLM only narrates preloaded output (Langflow-style),
without multi-turn tool orchestration or heavy reasoning.
"""

from __future__ import annotations

from typing import Any


def _week_by_description(plan_weeks: list[dict[str, Any]], desc: str) -> dict[str, Any] | None:
    for week in plan_weeks:
        if week.get("week_description") == desc:
            return week
    return None


def _latest_review_week(plan_weeks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Most recent week with completed actuals — prefer last past_week."""
    past = [w for w in plan_weeks if w.get("week_description") == "past_week"]
    if past:
        return past[-1]
    current = _week_by_description(plan_weeks, "current_week")
    if current and current.get("actuals", {}).get("distance_km") is not None:
        return current
    return None


def _acwr_label(acwr: float | None) -> str:
    if acwr is None:
        return "unknown"
    if acwr < 1.0:
        return "under_loading"
    if acwr <= 1.3:
        return "building"
    return "spike"


def _acwr_sentence(acwr: float | None) -> str:
    label = _acwr_label(acwr)
    if acwr is None:
        return "Load ratio unavailable — use distance and feel alongside planned targets."
    if label == "under_loading":
        return (
            f"ACWR {acwr} — under-loading / recovering; you can build again if "
            "intensity stays polarized."
        )
    if label == "building":
        return f"ACWR {acwr} — in the progressive overload zone; keep increases modest."
    return f"ACWR {acwr} — spike; hold or reduce volume before adding load."


def _intensity_assessment(actuals: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    easy = actuals.get("easy_pct")
    medium = actuals.get("medium_pct")
    hard = actuals.get("hard_pct")
    t_easy = target.get("easy_pct")
    t_hard = target.get("hard_pct")
    flags: list[str] = []
    if medium is not None and medium > 5:
        flags.append("medium_pct_creep")
    if easy is not None and t_easy is not None and easy > t_easy + 5:
        flags.append("too_easy")
    if hard is not None and t_hard is not None and hard < t_hard - 5:
        flags.append("under_hard")
    if hard is not None and t_hard is not None and hard > t_hard + 5:
        flags.append("over_hard")
    return {
        "easy_pct": easy,
        "medium_pct": medium,
        "hard_pct": hard,
        "target_easy_pct": t_easy,
        "target_medium_pct": target.get("medium_pct"),
        "target_hard_pct": t_hard,
        "flags": flags,
    }


def _volume_assessment(actuals: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    dist = actuals.get("distance_km")
    target_km = target.get("distance_km")
    if dist is None or target_km is None:
        return {"distance_km": dist, "target_km": target_km, "vs_target": None}
    delta = round(float(dist) - float(target_km), 2)
    if abs(delta) <= 2:
        vs = "on_target"
    elif delta > 0:
        vs = "above_target"
    else:
        vs = "below_target"
    return {"distance_km": dist, "target_km": target_km, "delta_km": delta, "vs_target": vs}


def _session_plan(week_type: str, target_km: int | None, acwr_label: str) -> list[dict[str, Any]]:
    """Polarized week skeleton — durations in minutes, no Zone 3."""
    if acwr_label == "spike" or week_type == "recovery":
        return [
            {"day_offset": 0, "session": "rest", "workout_type": None, "duration_min": None},
            {"day_offset": 1, "session": "recovery", "workout_type": "recovery", "duration_min": 30},
            {"day_offset": 2, "session": "rest", "workout_type": None, "duration_min": None},
            {"day_offset": 3, "session": "easy", "workout_type": "base", "duration_min": 35},
            {"day_offset": 4, "session": "rest", "workout_type": None, "duration_min": None},
            {"day_offset": 5, "session": "easy", "workout_type": "base", "duration_min": 40},
            {"day_offset": 6, "session": "easy", "workout_type": "long_run", "duration_min": 50},
        ]
    if week_type in ("taper_first", "taper_final", "race"):
        hard_tool = "sprint" if week_type == "race" else "threshold"
        hard_min = 25 if week_type == "taper_final" else 35
        return [
            {"day_offset": 0, "session": "rest", "workout_type": None, "duration_min": None},
            {"day_offset": 1, "session": "easy", "workout_type": "base", "duration_min": 30},
            {"day_offset": 2, "session": "easy", "workout_type": "recovery", "duration_min": 25},
            {"day_offset": 3, "session": "rest", "workout_type": None, "duration_min": None},
            {
                "day_offset": 4,
                "session": "quality",
                "workout_type": hard_tool,
                "duration_min": hard_min,
            },
            {"day_offset": 5, "session": "easy", "workout_type": "base", "duration_min": 25},
            {"day_offset": 6, "session": "easy", "workout_type": "long_run", "duration_min": 40},
        ]
    # build (default)
    hard_min = 45
    long_min = 70 if (target_km or 0) >= 25 else 55
    return [
        {"day_offset": 0, "session": "rest", "workout_type": None, "duration_min": None},
        {
            "day_offset": 1,
            "session": "quality",
            "workout_type": "threshold",
            "duration_min": hard_min,
        },
        {"day_offset": 2, "session": "recovery", "workout_type": "recovery", "duration_min": 30},
        {"day_offset": 3, "session": "easy", "workout_type": "base", "duration_min": 40},
        {"day_offset": 4, "session": "rest", "workout_type": None, "duration_min": None},
        {"day_offset": 5, "session": "easy", "workout_type": "base", "duration_min": 35},
        {
            "day_offset": 6,
            "session": "long",
            "workout_type": "long_run",
            "duration_min": long_min,
        },
    ]


def _attach_session_dates(
    sessions: list[dict[str, Any]], upcoming: dict[str, Any]
) -> list[dict[str, Any]]:
    days = upcoming.get("days") or []
    out: list[dict[str, Any]] = []
    for slot in sessions:
        row = dict(slot)
        offset = row.pop("day_offset", 0)
        if offset < len(days) and isinstance(days[offset], dict):
            day = days[offset]
            row["date"] = day.get("date")
            row["avg_temp_c"] = day.get("avg_temp_c")
            row["weather"] = day.get("weather")
            temp = day.get("avg_temp_c")
            if temp is not None and temp >= 28 and row.get("session") == "quality":
                row["heat_note"] = "Move quality to a cooler day if possible; coach by HR."
        out.append(row)
    return out


def _focus_for_week(week_type: str, intensity_flags: list[str], acwr_label: str) -> str:
    if acwr_label == "spike":
        return "Hold volume — easy aerobic only until ACWR settles."
    if "medium_pct_creep" in intensity_flags:
        return "Kill Zone 3 creep: easy days truly easy, quality clearly hard or skip."
    if week_type == "recovery":
        return "Recovery week — mostly easy Z1-2, one short quality touch at most."
    if week_type in ("taper_first", "taper_final"):
        return "Taper — maintain sharpness with short hard work, reduce overall volume."
    if week_type == "race":
        return "Race week — minimal volume, stay fresh."
    if "under_hard" in intensity_flags:
        return "Add one clear hard session; keep everything else easy."
    return "Build week — stay polarized: one hard stressor, rest truly easy."


def _narrative(
    review_week: dict[str, Any],
    upcoming: dict[str, Any] | None,
    assessment: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, str]:
    actuals = review_week.get("actuals") or {}
    target = review_week.get("target") or {}
    week_type = review_week.get("week_type", "build")
    dist = actuals.get("distance_km")
    target_km = target.get("distance_km")
    vol = assessment.get("volume") or {}

    review_bits = []
    if dist is not None:
        review_bits.append(f"{dist} km in a {week_type} week")
    if target_km is not None and vol.get("vs_target"):
        if vol["vs_target"] == "above_target":
            review_bits.append(f"above the plan target of {target_km} km")
        elif vol["vs_target"] == "below_target":
            review_bits.append(f"below the plan target of {target_km} km")
        else:
            review_bits.append(f"on the plan target of {target_km} km")
    review_summary = (
        "Your latest completed week was " + ", which is ".join(review_bits) + "."
        if review_bits
        else "No completed week data available yet."
    )

    intensity = assessment.get("intensity") or {}
    easy, medium, hard = intensity.get("easy_pct"), intensity.get("medium_pct"), intensity.get("hard_pct")
    t_easy, t_hard = intensity.get("target_easy_pct"), intensity.get("target_hard_pct")
    intensity_check = (
        f"Intensity split: easy {easy}% / medium {medium}% / hard {hard}% "
        f"(target ≈{t_easy}% easy / 0% medium / {t_hard}% hard)."
    )
    if "medium_pct_creep" in (intensity.get("flags") or []):
        intensity_check += " Medium (Zone 3) creep is the main fix — stay polarized."

    load_check = _acwr_sentence(actuals.get("acwr"))

    upcoming_type = (upcoming or {}).get("week_type", "build")
    upcoming_target = ((upcoming or {}).get("target") or {}).get("distance_km")
    proposal_summary = proposal.get("focus") or ""
    if upcoming_target is not None:
        proposal_summary = (
            f"Upcoming {upcoming_type} week target: {upcoming_target} km. {proposal_summary}"
        )

    return {
        "review_summary": review_summary,
        "intensity_check": intensity_check,
        "load_check": load_check,
        "proposal_summary": proposal_summary,
        "coaching_note": proposal.get("coaching_note", ""),
    }


def build_coaching_brief(
    training_plan: list[dict[str, Any]],
    events: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build review, assessment, next-week proposal, and ready-to-read narrative."""
    review_week = _latest_review_week(training_plan)
    upcoming = _week_by_description(training_plan, "upcoming_week")
    if not review_week:
        return {
            "error": "no_review_week",
            "message": "No past week data in training_plan to review.",
        }

    actuals = review_week.get("actuals") or {}
    target = review_week.get("target") or {}
    acwr = actuals.get("acwr")
    acwr_label = _acwr_label(acwr)
    intensity = _intensity_assessment(actuals, target)
    volume = _volume_assessment(actuals, target)

    upcoming_type = (upcoming or {}).get("week_type", "build")
    upcoming_target = ((upcoming or {}).get("target") or {}).get("distance_km")
    if acwr_label == "spike" and upcoming_type == "build":
        upcoming_type = "recovery"

    focus = _focus_for_week(upcoming_type, intensity.get("flags") or [], acwr_label)
    sessions = _attach_session_dates(
        _session_plan(upcoming_type, upcoming_target, acwr_label),
        upcoming or {},
    )

    coaching_note = focus
    if events and events.get("latest_event"):
        ev = events["latest_event"]
        coaching_note += f" Recent race: {ev.get('title')} ({ev.get('date')})."

    proposal = {
        "week_type": upcoming_type,
        "target_km": upcoming_target,
        "focus": focus,
        "sessions": sessions,
        "coaching_note": coaching_note,
    }

    assessment = {
        "intensity": intensity,
        "volume": volume,
        "acwr": acwr,
        "acwr_label": acwr_label,
    }

    narrative = _narrative(review_week, upcoming, assessment, proposal)

    return {
        "review_week": {
            "week_description": review_week.get("week_description"),
            "week_type": review_week.get("week_type"),
            "actuals": actuals,
            "target": target,
        },
        "upcoming_week": {
            "week_type": upcoming_type,
            "target": upcoming.get("target") if upcoming else None,
        },
        "assessment": assessment,
        "next_week_proposal": proposal,
        "narrative": narrative,
        "presentation_order": [
            "review_summary",
            "intensity_check",
            "load_check",
            "proposal_summary",
            "coaching_note",
        ],
    }
