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
    """Per-day weather context for the agent — no workout prescriptions."""
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
    dist = actuals.get("distance_km")
    target_km = target.get("distance_km")
    total_zone = actuals.get("total_zone_min")
    if dist is None or target_km is None:
        return {
            "distance_km": dist,
            "target_km": target_km,
            "total_zone_min": total_zone,
            "vs_target": None,
        }
    # Cross-training weeks can have zone time with ~0 run km — don't judge km.
    if float(dist) <= 0 and total_zone is not None and float(total_zone) > 0:
        return {
            "distance_km": dist,
            "target_km": target_km,
            "total_zone_min": total_zone,
            "vs_target": None,
            "note": "cross_training_time",
        }
    delta = round(float(dist) - float(target_km), 2)
    if abs(delta) <= 2:
        vs = "on_target"
    elif delta > 0:
        vs = "above_target"
    else:
        vs = "below_target"
    return {
        "distance_km": dist,
        "target_km": target_km,
        "total_zone_min": total_zone,
        "delta_km": delta,
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
) -> dict[str, str]:
    actuals = review_week.get("actuals") or {}
    target = review_week.get("target") or {}
    week_type = review_week.get("week_type", "build")
    dist = actuals.get("distance_km")
    total_zone = actuals.get("total_zone_min")
    target_km = target.get("distance_km")
    vol = assessment.get("volume") or {}

    review_bits = []
    # Prefer time-in-zone when run distance is absent/zero but HR time exists
    # (cross-training / non-run weeks).
    has_run_distance = dist is not None and float(dist) > 0
    has_zone_time = total_zone is not None and float(total_zone) > 0
    if has_run_distance:
        review_bits.append(f"{dist} km in a {week_type} week")
    elif has_zone_time:
        review_bits.append(f"{total_zone} min training time in a {week_type} week")
    elif dist is not None:
        review_bits.append(f"{dist} km in a {week_type} week")
    if target_km is not None and vol.get("vs_target"):
        if vol["vs_target"] == "above_target":
            review_bits.append(f"above the plan target of {target_km} km")
        elif vol["vs_target"] == "below_target":
            review_bits.append(f"below the plan target of {target_km} km")
        else:
            review_bits.append(f"on the plan target of {target_km} km")
    if review_bits:
        review_summary = (
            "Your latest 7 days (through yesterday) were "
            + ", which is ".join(review_bits)
            + "."
        )
        if has_run_distance and has_zone_time:
            review_summary = (
                review_summary[:-1] + f" ({total_zone} min in HR zones)."
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
    personal_records_summary = _personal_records_summary(personal_records)

    upcoming_type = (upcoming or {}).get("week_type", "build")
    upcoming_target = ((upcoming or {}).get("target") or {}).get("distance_km")
    proposal_summary = proposal.get("focus") or ""
    proposal_target_km = proposal.get("target_km")
    proposal_week_type = proposal.get("week_type", upcoming_type)
    if proposal_target_km is not None:
        proposal_summary = (
            f"Upcoming {proposal_week_type} week target: {proposal_target_km} km. "
            f"{proposal_summary}"
        )
    elif upcoming_target is not None:
        proposal_summary = (
            f"Upcoming {upcoming_type} week target: {upcoming_target} km. {proposal_summary}"
        )

    return {
        "review_summary": review_summary,
        "intensity_check": intensity_check,
        "load_check": load_check,
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
    planned_target_km = ((upcoming or {}).get("target") or {}).get("distance_km")
    upcoming_target = planned_target_km
    if acwr_label == "spike" and upcoming_type == "build":
        upcoming_type = "recovery"
        # Use explicit None-check so cross-training weeks with 0 run km do not
        # fall through to the (often large) planned running target.
        dist_km = actuals.get("distance_km")
        base_km = float(dist_km) if dist_km is not None else planned_target_km
        if base_km is not None:
            deload_km = round(float(base_km) * 0.8)
            if planned_target_km is not None:
                deload_km = min(deload_km, int(planned_target_km))
            upcoming_target = deload_km

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

    narrative = _narrative(
        review_week,
        upcoming,
        assessment,
        proposal,
        personal_records=personal_records,
    )

    upcoming_target_block = dict((upcoming or {}).get("target") or {})
    if upcoming_target is not None:
        upcoming_target_block["distance_km"] = upcoming_target

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
        },
        "assessment": assessment,
        "next_week_proposal": proposal,
        "narrative": narrative,
        "presentation_order": [
            "review_summary",
            "intensity_check",
            "load_check",
            "personal_records_summary",
            "proposal_summary",
            "coaching_note",
        ],
    }
