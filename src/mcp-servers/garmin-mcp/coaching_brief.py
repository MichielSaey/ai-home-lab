"""Deterministic coaching brief — review, assessment, and next-week proposal.

Computed server-side for past-week analysis and next-week context including
session prescriptions (minutes). The agent narrates the brief and may upload
workouts via create_*_workout using sessions[] and session_targets.
"""

from __future__ import annotations

from typing import Any

from training_plan import split_week_sessions

# Maps next_week_proposal.sessions[].session_type to the MCP upload tool.
# Threshold stays on the HR-zone template; sprints are the pace+distance exception.
SESSION_TARGETS: dict[str, dict[str, str]] = {
    "easy": {"tool": "create_base_workout", "target": "HR zone 2"},
    "long": {"tool": "create_long_run_workout", "target": "HR zone 2"},
    "recovery": {"tool": "create_recovery_workout", "target": "HR zone 1"},
    "threshold": {"tool": "create_threshold_workout", "target": "HR zone 4"},
    "sprint": {"tool": "create_sprint_workout", "target": "pace + distance"},
    "hill_repeats": {
        "tool": "create_hill_repeats_workout",
        "target": "pace + distance",
    },
    "weighted_pack": {
        "tool": "create_weighted_pack_workout",
        "target": "HR zone 2",
    },
}


def _week_by_description(plan_weeks: list[dict[str, Any]], desc: str) -> dict[str, Any] | None:
    for week in plan_weeks:
        if week.get("week_description") == desc:
            return week
    return None


def _latest_review_week(plan_weeks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Most recent rolling 7-day block (yesterday … yesterday−6)."""
    latest = _week_by_description(plan_weeks, "latest_week")
    if latest:
        actuals = latest.get("actuals") or {}
        if (
            actuals.get("distance_km") is not None
            or actuals.get("total_zone_min") is not None
        ):
            return latest
    past = [w for w in plan_weeks if w.get("week_description") == "past_week"]
    if past:
        return past[-1]
    return None


def _proposal_days(upcoming: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-day weather context for the agent."""
    days = (upcoming or {}).get("days") or []
    out: list[dict[str, Any]] = []
    for day in days:
        if not isinstance(day, dict) or day.get("date") is None:
            continue
        out.append(
            {
                "date": day["date"],
                "avg_temp_c": day.get("avg_temp_c"),
                "weather": day.get("weather"),
            }
        )
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
        return "Load ratio unavailable — use training time and feel alongside planned targets."
    if label == "under_loading":
        return (
            f"ACWR {acwr} — under-loading / recovering; you can build again if "
            "intensity stays polarized."
        )
    if label == "building":
        return f"ACWR {acwr} — in the progressive overload zone; keep increases modest."
    return f"ACWR {acwr} — spike; hold or reduce volume before adding load."


def _activity_self_evaluation_text(act: dict[str, Any]) -> str | None:
    """Written note on an activity. ``self_evaluation`` is free text, not a score."""
    note = act.get("self_evaluation")
    if isinstance(note, str) and note.strip():
        return note.strip()
    return None


def _self_evaluation_notes(recent_activities: list[dict[str, Any]] | None) -> str:
    """Recap this week's written self-evaluation notes (scores are secondary)."""
    if not recent_activities:
        return "No athlete self-evaluation notes for this week."
    lines: list[str] = []
    for act in recent_activities:
        if not isinstance(act, dict):
            continue
        note = _activity_self_evaluation_text(act)
        feeling = act.get("feeling")
        effort = act.get("perceived_effort")
        if not note and not feeling and effort is None:
            continue
        name = act.get("name") or act.get("activity_type") or "activity"
        date_s = act.get("date") or ""
        prefix = f"{date_s} {name}".strip()
        extras: list[str] = []
        if feeling:
            extras.append(str(feeling))
        if effort is not None:
            extras.append(f"RPE {effort}")
        extra = f" ({', '.join(extras)})" if extras else ""
        if note:
            lines.append(f"{prefix}: {note}{extra}")
        else:
            lines.append(f"{prefix}:{extra}" if extra else prefix)
    if not lines:
        return "No athlete self-evaluation notes for this week."
    return "Athlete self-evaluation this week — " + " | ".join(lines) + "."


def _cross_training_note(recent_activities: list[dict[str, Any]] | None) -> str:
    if not recent_activities:
        return ""
    non_run: list[str] = []
    for act in recent_activities:
        if not isinstance(act, dict):
            continue
        sport = str(act.get("activity_type") or "").lower()
        if not sport or sport in ("running", "trail_running", "treadmill_running"):
            continue
        minutes = act.get("duration_min")
        name = act.get("name") or sport
        if minutes is not None:
            non_run.append(f"{name} ({minutes} min)")
        else:
            non_run.append(str(name))
    if not non_run:
        return ""
    shown = "; ".join(non_run[:5])
    extra = f" (+{len(non_run) - 5} more)" if len(non_run) > 5 else ""
    return (
        f" Cross-training in recent activities (counts toward weekly time): "
        f"{shown}{extra}."
    )


def _intensity_assessment(actuals: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    easy = actuals.get("easy_pct")
    medium = actuals.get("medium_pct")
    hard = actuals.get("hard_pct")
    z4 = actuals.get("zone_4_pct")
    z5 = actuals.get("zone_5_pct")
    t_easy = target.get("easy_pct")
    t_hard = target.get("hard_pct")
    t_z4 = target.get("zone_4_pct")
    t_z5 = target.get("zone_5_pct")
    flags: list[str] = []
    if medium is not None and medium > 5:
        flags.append("medium_pct_creep")
    if easy is not None and t_easy is not None and easy > t_easy + 5:
        flags.append("too_easy")
    if hard is not None and t_hard is not None and hard < t_hard - 5:
        flags.append("under_hard")
    if hard is not None and t_hard is not None and hard > t_hard + 5:
        flags.append("over_hard")
    if z4 is not None and t_z4 is not None and z4 < t_z4 - 5:
        flags.append("under_zone_4")
    if z5 is not None and t_z5 is not None and z5 < max(1.0, t_z5 - 2):
        flags.append("under_zone_5")
        flags.append("under_sprint")
    return {
        "easy_pct": easy,
        "medium_pct": medium,
        "hard_pct": hard,
        "zone_4_pct": z4,
        "zone_5_pct": z5,
        "target_easy_pct": t_easy,
        "target_medium_pct": target.get("medium_pct"),
        "target_hard_pct": t_hard,
        "target_zone_4_pct": t_z4,
        "target_zone_5_pct": t_z5,
        "flags": flags,
    }


def _volume_assessment(actuals: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    total_zone = actuals.get("total_zone_min")
    target_min = target.get("target_min")
    dist = actuals.get("distance_km")
    if total_zone is None or target_min is None:
        return {
            "total_zone_min": total_zone,
            "target_min": target_min,
            "distance_km": dist,
            "vs_target": None,
        }
    delta = round(float(total_zone) - float(target_min), 2)
    if abs(delta) <= 15:
        vs = "on_target"
    elif delta > 0:
        vs = "above_target"
    else:
        vs = "below_target"
    return {
        "total_zone_min": total_zone,
        "target_min": target_min,
        "distance_km": dist,
        "delta_min": delta,
        "vs_target": vs,
    }


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
    if "under_sprint" in intensity_flags or "under_zone_5" in intensity_flags:
        return (
            "Include short Z5 sprint work in the quality budget; keep easy days easy."
        )
    if "under_zone_4" in intensity_flags or "under_hard" in intensity_flags:
        return "Add one clear Z4 threshold session; keep everything else easy."
    return "Build week — stay polarized: ~80% easy / 15% Z4 / 5% Z5."


def _personal_records_summary(personal_records: dict[str, Any] | None) -> str:
    if not personal_records:
        return "Personal records unavailable."
    if personal_records.get("error"):
        return "Personal records unavailable."
    records = personal_records.get("records")
    if isinstance(records, list) and records:
        bits: list[str] = []
        for record in records[:5]:
            if not isinstance(record, dict):
                continue
            label = record.get("label") or "PR"
            display = record.get("display_value")
            if display is None:
                display = record.get("value")
            pr_date = record.get("date")
            piece = f"{label}: {display}" if display is not None else str(label)
            if pr_date:
                piece += f" ({pr_date})"
            bits.append(piece)
        if not bits:
            return personal_records.get("summary") or "No personal records on file."
        extra = f" (+{len(records) - 5} more)" if len(records) > 5 else ""
        return "Personal records — " + "; ".join(bits) + extra + "."
    summary = personal_records.get("summary")
    if isinstance(summary, str) and summary:
        return summary
    return "No personal records on file."


def _positive_minutes(value: Any) -> float | None:
    if value is None:
        return None
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def _time_intensity_overview(actuals: dict[str, Any]) -> str:
    """Primary intensity overview in minutes (workout-type independent)."""
    total = _positive_minutes(actuals.get("total_zone_min"))
    zone_values = [
        ("Z1", _positive_minutes(actuals.get("zone_1_min"))),
        ("Z2", _positive_minutes(actuals.get("zone_2_min"))),
        ("Z3", _positive_minutes(actuals.get("zone_3_min"))),
        ("Z4", _positive_minutes(actuals.get("zone_4_min"))),
        ("Z5", _positive_minutes(actuals.get("zone_5_min"))),
    ]
    if total is None and all(value is None for _, value in zone_values):
        return "Time-in-zone data unavailable for the latest block."
    parts: list[str] = []
    if total is not None:
        parts.append(f"{total} min total in HR zones")
    zone_bits = [f"{label} {value}" for label, value in zone_values if value is not None]
    if zone_bits:
        parts.append("minutes: " + " / ".join(zone_bits))
    return "Time-based intensity — " + "; ".join(parts) + "."


def _narrative(
    review_week: dict[str, Any],
    upcoming: dict[str, Any] | None,
    assessment: dict[str, Any],
    proposal: dict[str, Any],
    personal_records: dict[str, Any] | None = None,
    recent_activities: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    actuals = review_week.get("actuals") or {}
    target = review_week.get("target") or {}
    week_type = review_week.get("week_type", "build")
    total_zone = actuals.get("total_zone_min")
    target_min = target.get("target_min")
    vol = assessment.get("volume") or {}

    review_bits = []
    has_zone_time = total_zone is not None and float(total_zone) > 0
    if has_zone_time:
        review_bits.append(f"{total_zone} min training time in a {week_type} week")
    if target_min is not None and vol.get("vs_target"):
        if vol["vs_target"] == "above_target":
            review_bits.append(f"above the plan target of {target_min} min")
        elif vol["vs_target"] == "below_target":
            review_bits.append(f"below the plan target of {target_min} min")
        else:
            review_bits.append(f"on the plan target of {target_min} min")
    if review_bits:
        review_summary = (
            "Your latest 7 days (through yesterday) were "
            + ", which is ".join(review_bits)
            + "."
        )
    else:
        review_summary = "No completed 7-day block data available yet."

    intensity = assessment.get("intensity") or {}
    easy = intensity.get("easy_pct")
    medium = intensity.get("medium_pct")
    z4 = intensity.get("zone_4_pct")
    z5 = intensity.get("zone_5_pct")
    t_easy = intensity.get("target_easy_pct")
    t_z4 = intensity.get("target_zone_4_pct")
    t_z5 = intensity.get("target_zone_5_pct")
    time_overview = _time_intensity_overview(actuals)
    intensity_check = (
        f"{time_overview} Intensity split: easy {easy}% / medium {medium}% / "
        f"Z4 {z4}% / Z5 {z5}% "
        f"(target ≈{t_easy}% easy / 0% medium / {t_z4}% Z4 / {t_z5}% Z5)."
    )
    if "medium_pct_creep" in (intensity.get("flags") or []):
        intensity_check += " Medium (Zone 3) creep is the main fix — stay polarized."
    if "under_sprint" in (intensity.get("flags") or []):
        intensity_check += " Sprint (Z5) share is light — keep a small Z5 budget."

    load_check = _acwr_sentence(actuals.get("acwr"))
    load_check += _cross_training_note(recent_activities)
    self_evaluation_notes = _self_evaluation_notes(recent_activities)

    chronic = proposal.get("chronic_min")
    outliers = proposal.get("outlier_weeks_dropped") or []
    if chronic is not None and outliers:
        load_check += (
            f" Chronic volume {chronic} min (dropped {len(outliers)} outlier "
            "week(s) beyond 50% of the median)."
        )
    elif chronic is not None:
        load_check += f" Chronic volume {chronic} min."

    personal_records_summary = _personal_records_summary(personal_records)

    upcoming_type = (upcoming or {}).get("week_type", "build")
    upcoming_target = ((upcoming or {}).get("target") or {}).get("target_min")
    proposal_summary = proposal.get("focus") or ""
    proposal_target_min = proposal.get("target_min")
    proposal_week_type = proposal.get("week_type", upcoming_type)
    if proposal_target_min is not None:
        proposal_summary = (
            f"Upcoming {proposal_week_type} week target: {proposal_target_min} min. "
            f"{proposal_summary}"
        )
    elif upcoming_target is not None:
        proposal_summary = (
            f"Upcoming {upcoming_type} week target: {upcoming_target} min. "
            f"{proposal_summary}"
        )
    sessions = proposal.get("sessions") or []
    if sessions:
        proposal_summary += f" Proposed {len(sessions)} sessions from the minute budget."

    return {
        "review_summary": review_summary,
        "intensity_check": intensity_check,
        "load_check": load_check,
        "self_evaluation_notes": self_evaluation_notes,
        "personal_records_summary": personal_records_summary,
        "proposal_summary": proposal_summary,
        "coaching_note": proposal.get("coaching_note", ""),
    }


def build_coaching_brief(
    training_plan: list[dict[str, Any]],
    events: dict[str, Any] | None = None,
    recent_activities: list[dict[str, Any]] | None = None,
    personal_records: dict[str, Any] | None = None,
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
    planned_target_min = ((upcoming or {}).get("target") or {}).get("target_min")
    chronic_min = (upcoming or {}).get("chronic_min")
    outliers = list((upcoming or {}).get("outlier_weeks_dropped") or [])
    upcoming_target = planned_target_min

    if acwr_label == "spike" and upcoming_type == "build":
        upcoming_type = "recovery"
        if chronic_min is not None:
            upcoming_target = round(float(chronic_min) * 0.80)
        elif planned_target_min is not None:
            # Planned was build (C×1.15); recovery equivalent ≈ C×0.80.
            upcoming_target = round(float(planned_target_min) * 0.80 / 1.15)

    focus = _focus_for_week(upcoming_type, intensity.get("flags") or [], acwr_label)
    days = _proposal_days(upcoming)
    sessions = split_week_sessions(upcoming_target, upcoming_type, days)

    coaching_note = focus
    if events and events.get("latest_event"):
        ev = events["latest_event"]
        coaching_note += f" Recent race: {ev.get('title')} ({ev.get('date')})."

    proposal = {
        "week_type": upcoming_type,
        "target_min": upcoming_target,
        "chronic_min": chronic_min,
        "outlier_weeks_dropped": outliers,
        "focus": focus,
        "days": days,
        "sessions": sessions,
        "session_targets": SESSION_TARGETS,
        "coaching_note": coaching_note,
    }

    assessment = {
        "intensity": intensity,
        "volume": volume,
        "acwr": acwr,
        "acwr_label": acwr_label,
    }

    narrative = _narrative(
        review_week,
        upcoming,
        assessment,
        proposal,
        personal_records=personal_records,
        recent_activities=recent_activities,
    )

    upcoming_target_block = dict((upcoming or {}).get("target") or {})
    if upcoming_target is not None:
        upcoming_target_block["target_min"] = upcoming_target

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
            "target": upcoming_target_block or None,
            "chronic_min": chronic_min,
            "outlier_weeks_dropped": outliers,
        },
        "assessment": assessment,
        "next_week_proposal": proposal,
        "narrative": narrative,
        "presentation_order": [
            "review_summary",
            "intensity_check",
            "load_check",
            "self_evaluation_notes",
            "personal_records_summary",
            "proposal_summary",
            "coaching_note",
        ],
    }
