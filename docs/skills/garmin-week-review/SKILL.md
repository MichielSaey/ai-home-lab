---
name: garmin-week-review
description: "Garmin week review via get_coaching_brief — ACWR, time-in-zone intensity, next-week proposal (garmin-mcp, agent mode)."
version: 2.5.0
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
intensity feedback (Z1–Z5), next-week proposals. **Agent mode only.**

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
3. Propose a day-by-day workout plan yourself using:
   - `next_week_proposal.week_type`, `target_km`, `focus`, `coaching_note`
   - `next_week_proposal.days` for date, `avg_temp_c`, and `weather` (move hard
     sessions off hot days when `avg_temp_c` ≥ 28)
   - `recent_activities` when relevant (e.g. recovery run yesterday → avoid
     stacking recovery today)
4. Call `create_*_workout` only when the user asks to upload workouts to Garmin
   Connect (optional `workout_date`).

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
- Recovery-week volume target is **80% of your peak build-week km**, not the partial latest block.
- Polarized easy + quality: ≈80% Z1-2 / 0% Z3 / 15% Z4 / 5% Z5 (build week) — no Zone 3 / tempo prescriptions.
- Do not ask the user to paste Garmin data.

## Verification

- First garmin MCP tool in the transcript ends with `get_coaching_brief`.
- Numbers from `coaching_brief.narrative`, not placeholders.
- Workout plan is agent-authored from `next_week_proposal` context and `days` weather.
