# Garmin MCP — tools

Personal coach stack: one read tool, atomic helpers, workout actions.

## Coaching

| Tool | Purpose |
|------|---------|
| **`get_coaching_brief`** | **Only tool for week review.** Profile, events, predictions, personal records, `training_plan`, `coaching_brief` (narrative + next-week context). |
| `get_report` | Same data shape with `days` / `days_ago` window — ends on yesterday for the default 7-day review block (today excluded from rollups). |

## Athlete context (narrow questions)

| Tool | Purpose |
|------|---------|
| `get_profile` | Age, VO2 max, thresholds, weight |
| `get_events` | Upcoming races + `latest_event` (past 28 days) |
| `get_race_predictions` | Garmin predicted race times |
| `get_personal_records` | Running PRs for coaching: 5K, 10K, half, marathon, longest run (drops 1K/mile/steps/etc.) |

All four are already inside `get_coaching_brief`.

## Raw data (debugging)

| Tool | Purpose |
|------|---------|
| `get_weekly_stats` | Weekly distance + time-in-zone table (all activity types) — rolling 7-day blocks through yesterday; includes `total_zone_min`; optional `end_date` is the latest block anchor (not today). |
| `get_activities` | Activity list (all types) with optional HR zones |

## Workouts (schedule on Garmin)

| Tool | Purpose |
|------|---------|
| `create_base_workout` | Easy Z2 aerobic |
| `create_recovery_workout` | Z1 recovery |
| `create_long_run_workout` | Long easy |
| `create_threshold_workout` | Z4 threshold repeats (`repetitions`, `interval_minutes`, 2 min recovery default). HR zone 4 on efforts. |
| `create_sprint_workout` | Distance sprints with speed (m/s) targets |
| `create_hill_repeats_workout` | Hill distance sprints with speed targets |
| `create_weighted_pack_workout` | Loaded pack / ruck |
| `combine_workout_templates` | Hybrid session from **named** templates (e.g. base + sprints). Not a freeform step builder. |
| `schedule_workout` | Schedule existing workout by ID |
| `list_workout_templates` | Built-in template catalog |
| `get_workouts` | Saved library workouts |

`create_*` accepts optional `workout_date` (`YYYY-MM-DD`) to upload and schedule in one call.

## Reference

| Tool | Purpose |
|------|---------|
| `get_garmin_health` | Auth/connectivity check |
| `get_heart_rate_zones` | Zones used by templates |
| `get_nutrition_cues` | Fueling hints for a duration |

## `get_coaching_brief` response

- `profile`, `race_predictions`, `personal_records`, `events`
- **`training_plan`** — week rows (past, current, upcoming): actuals (distance + zone minutes + intensity pcts including Z4/Z5), targets (≈80/15/5 for build weeks), load, weather
- **`coaching_brief`** — `narrative` (includes `personal_records_summary` and a time-based intensity overview), `assessment`, `next_week_proposal` (week_type, `target_min`, `chronic_min`, `outlier_weeks_dropped`, `sessions[]`, `session_targets` mapping session_type → upload tool + intensity target, focus, per-day weather in `days`), `recent_activities` (all sports with `activity_type` + `duration_min`)
- `window` — default 7-day review ends **yesterday** (today may appear only in `recent_activities`)
- optional `activities`

Coaching rules live in `coaching_brief.py` and `training_plan.py` (not a separate prompt tool). Intensity targets are polarized easy + quality with hard split **≈15% Z4 / 5% Z5** (build week; other week types keep the same 75/25 hard split). Upload threshold with `create_threshold_workout` (HR Z4); sprints use pace + distance. Hybrid days use `combine_workout_templates` with named templates only.

## REST (n8n)

- `GET /coaching-brief` — primary
- `GET /weekly-report` — same handler (legacy path)
- `GET /health`

## MCP clients

Any MCP client (Open WebUI or similar) uses these tools directly. Week review is one `get_coaching_brief` call; uploads use `create_*_workout` / `combine_workout_templates`.
