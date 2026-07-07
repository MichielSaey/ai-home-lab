"""Deterministic coaching brief — review, assessment, and next-week context.

Computed server-side for past-week analysis and high-level proposal context.
The agent (LLM) proposes day-by-day workouts using week_type, targets, focus,
and per-day weather — not pre-filled session prescriptions.
"""

from __future__ import annotations

from typing import Any


def _week_by_description(plan_weeks: list[dict[str, Any]], desc: str) -> dict[str, Any] | None:
    for week in plan_weeks:
        if week.get("week_description") == desc:
            return week
    return None


def _latest_review_week(plan_weeks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Most recent rolling 7-day block (yesterday … yesterday−6)."""
    latest = _week_by_description(plan_weeks, "latest_week")
    if latest and latest.get("actuals", {}).get("distance_km") is not None:
        return latest
    past = [w for w in plan_weeks if w.get("week_description") == "past_week"]
    if past:
        return past[-1]
    return None


def _proposal_days(upcoming: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-day weather context for the agent — no workout prescriptions."""
    days = (upcoming or {}).get("days") or []
    out: list[dict[str, Any]] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        row: dict[str, Any] = {}
        if day.get("date") is not None:
            row["date"] = day["date"]
        if day.get("avg_temp_c") is not None:
            row["avg_temp_c"] = day["avg_temp_c"]
        if day.get("weather") is not None:
            row["weather"] = day["weather"]
        if row:
            out.append(row)
    return out


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
        "Your latest 7 days (through yesterday) were "
        + ", which is ".join(review_bits)
        + "."
        if review_bits
        else "No completed 7-day block data available yet."
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
    recent_activities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build review, assessment, next-week context, and ready-to-read narrative."""
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
    days = _proposal_days(upcoming)

    coaching_note = focus
    if events and events.get("latest_event"):
        ev = events["latest_event"]
        coaching_note += f" Recent race: {ev.get('title')} ({ev.get('date')})."

    proposal = {
        "week_type": upcoming_type,
        "target_km": upcoming_target,
        "focus": focus,
        "days": days,
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
        "recent_activities": recent_activities or [],
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
