---
name: garmin-profile
description: Garmin profile — athlete stats, races, and pace predictions.
version: 1.0.0
category: health
tags: [running, garmin, profile, races]
requires_toolsets: [garmin-mcp]
status: published
source: taught
---

## When to Use

Fetch Garmin athlete context: profile (age, VO2 max, thresholds), upcoming
events, race predictions, and personal records. Use when the user asks who they
are as an athlete, what races are on the calendar, what paces Garmin predicts,
or what PRs they hold. **Agent mode only.** Example:
`/garmin-profile show my profile and races`.

## Procedure

1. Call `get_profile` — age, VO2 max, lactate threshold HR/pace, and related
   stats.
2. Call `get_events` — upcoming races with dates and distances.
3. Call `get_race_predictions` — predicted times for standard distances.
4. Call `get_personal_records` — PRs from Garmin Connect when relevant.
5. Present a short structured summary (profile → events → predictions → PRs).
   If the user asked a narrow question, answer that part first.

## Pitfalls

- Do not ask the user to paste Connect screenshots.
- If a tool errors, report the error; do not invent stats.

## Verification

- Numbers match tool output (VO2 max, event dates, prediction times).
