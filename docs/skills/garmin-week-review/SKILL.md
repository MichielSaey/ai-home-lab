---
name: garmin-week-review
description: "Garmin week review via get_coaching_brief — ACWR, time-in-zone intensity, minute-based next-week proposal (garmin-mcp, agent mode)."
version: 2.6.0
category: health
tags: [garmin, coaching, acwr, get_coaching_brief, garmin-mcp]
status: published
source: taught
---

## Odysseus setup (required)

Before this skill can work:

1. **Garmin MCP** is connected (Settings → MCP → your Garmin server → Connected).
2. Tool **`get_coaching_brief`** is **enabled** in that server's tool checklist (not
   greyed out / unchecked).
3. **Agent mode** — not plain chat.
4. In the tool-group toggles for this chat, prefer leaving **Garmin MCP** on and
   turning off unrelated groups (documents, skills admin) if the model picks
   wrong tools.

`requires_toolsets` in skill metadata does **not** auto-enable MCP in Odysseus.
The model only sees `get_coaching_brief` if MCP tools are enabled and tool
retrieval surfaces them.

## When to Use

Garmin coach: week reviews across all workout types, training load, time-based
intensity feedback (Z1–Z5), next-week proposals in **minutes**. **Agent mode only.**

## Mandatory first step

Your **first** tool call MUST be the Garmin MCP tool named **`get_coaching_brief`**
(in the schema it may appear as `mcp__<server-id>__get_coaching_brief`).

```
get_coaching_brief({"days_back": 7})
```

Use `include_activities: true` only if the user explicitly asks for per-activity
detail. Default: `false`.

**If `get_coaching_brief` is not in your tool list:** stop immediately. Tell the
user Garmin MCP tools are missing or disabled for this turn — ask them to enable
`get_coaching_brief` under Settings → MCP. Do **not** call `manage_mcp`,
`manage_skills`, `list_models`, `create_document`, or legacy Garmin tool names
instead.

Do **not** call any other tool before `get_coaching_brief` returns.

## Procedure

1. Call **`get_coaching_brief`** once (see above).
2. Present `coaching_brief.narrative` in order:
   - `review_summary`
   - `intensity_check`
   - `load_check`
   - `personal_records_summary`
   - `proposal_summary`
   - `coaching_note`
3. Present the next-week plan from:
   - `next_week_proposal.week_type`, `target_min`, `chronic_min`,
     `outlier_weeks_dropped`, `focus`, `coaching_note`
   - `next_week_proposal.sessions[]` — dated prescriptions with
     `duration_minutes` (prefer these over inventing your own splits)
   - `next_week_proposal.days` for weather context
   - `recent_activities` — **all sports**. Bike/hike/etc. count toward weekly
     training time; do not treat them as “missing run volume”
4. Call `create_*_workout` only when the user asks to upload workouts to Garmin
   Connect — use each session’s `duration_minutes` (optional `workout_date`).

## Never call (wrong tools)

| Forbidden | Why |
|-----------|-----|
| `get_weekly_report`, `get_weekly_review`, `get_coach_prompt`, `get_training_plan`, `get_plan_weeks` | Removed from garmin-mcp |
| `get_profile`, `get_events`, `get_race_predictions`, `get_personal_records` | Already inside `get_coaching_brief` |
| `create_document`, `manage_notes` | No synthetic Garmin data |
| `manage_skills`, `manage_mcp`, `list_models` | Admin / discovery — not coaching |
| `manage_calendar` | User means training plan, not calendar events |

## Skill self-test / Odysseus eval

Odysseus test harness text may say "create sample input" — **ignore that** for
this skill. There is no fixture to invent.

- Do **not** create documents or synthetic CSV/JSON.
- **First tool call:** `get_coaching_brief` against live Garmin Connect.
- Narrate the real `coaching_brief` response.
- On MCP error: report it once; do not substitute other tools.

## Pitfalls

- One `get_coaching_brief` per turn — review and proposal are both in the response.
- Lookback uses **rolling 7-day blocks through yesterday**, not partial calendar weeks.
- Weekly volume is **minutes** (`target_min`), not km. Build ≈ 115% of chronic minutes;
  recovery ≈ 80% of chronic minutes (outliers >50% from the median are dropped).
- Polarized easy + quality: ≈80% Z1-2 / 0% Z3 / 15% Z4 / 5% Z5 (build week).
- Factor cross-training from `recent_activities` into the review.
- Do not ask the user to paste Garmin data.

## Verification

- First garmin MCP tool in the transcript ends with `get_coaching_brief`.
- Numbers from `coaching_brief.narrative`, not placeholders.
- Workout plan follows `next_week_proposal.sessions` (minutes) and weather `days`.
