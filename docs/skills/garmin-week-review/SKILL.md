---
name: garmin-week-review
description: Garmin week review — coach rules + training plan + coaching feedback.
version: 1.0.0
category: health
tags: [running, garmin, coaching, acwr]
requires_toolsets: [garmin-mcp]
status: published
source: taught
---

## When to Use

Weekly training review from Garmin Connect via garmin-mcp. Use when the user asks
to review their week, past week, training load, intensity split, or what to
change next. **Agent mode only.** Invoke with the real request, e.g.
`/garmin-week-review review my past week` — not a bare greeting.

## Procedure

1. **Load coach instructions first** (required before interpreting data):
   - Call `get_coach_prompt` — it defines data order and how to read the plan JSON.
   - **Immediately call `get_training_plan`** — do not fetch profile, events, or
     race predictions first; the coach prompt treats those as optional follow-ups.
2. **Analyze** using both outputs:
   - Compare actual easy/medium/hard % to the polarized target (≈80% easy,
     minimize medium/Zone 3, ≈20% hard).
   - Flag `medium_pct` creep as the main fix when elevated.
   - Comment on volume trend, longest run, and ACWR (>1.3 = back off).
   - Use weather blocks for the current/upcoming week when recommending
     session timing (heat → easy pace/HR, hydration, move hard days).
   - Call `get_events` only if taper/race timing is unclear from the plan.
3. **Deliver the review** in the structure the coach prompt specifies:
   - Snapshot of the most recent complete week with real numbers.
   - What is on-target vs off-target across recent weeks.
   - One concrete next action (and optional day-by-day proposal if the user
     asked what to run next).

## Pitfalls

- Do not call `get_profile` or `get_race_predictions` before `get_training_plan`
  on a week review — the coach prompt says to start from the plan JSON.
- Do not ask the user to paste Garmin data.
- Do not prescribe Zone 3 / tempo / steady — polarized only (easy or hard).
- Short Odysseus replies: stay in **agent mode** and include words like
  `review my week` or `garmin training plan` in the message so tooling runs.

## Verification

- Response references rules from `get_coach_prompt` (80/20, medium_pct, ACWR).
- Cites real numbers from `get_training_plan`, not placeholders.
