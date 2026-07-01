# Garmin MCP — tools

Personal coach stack: one read tool, atomic helpers, workout actions.

## Coaching

| Tool | Purpose |
|------|---------|
| **`get_coaching_brief`** | **Only tool for week review.** Profile, events, predictions, `training_plan`, `coaching_brief` (narrative + next-week sessions). |
| `get_report` | Same data shape with `days` / `days_ago` window — for shifted lookback, not normal coaching. |

## Athlete context (profile skill / narrow questions)

| Tool | Purpose |
|------|---------|
| `get_profile` | Age, VO2 max, thresholds, weight |
| `get_events` | Upcoming races + `latest_event` (past 28 days) |
| `get_race_predictions` | Garmin predicted race times |

All three are already inside `get_coaching_brief`.

## Raw data (debugging)

| Tool | Purpose |
|------|---------|
| `get_weekly_stats` | Weekly distance + HR zone table — no targets or periodization |
| `get_activities` | Activity list with optional HR zones |

## Workouts (schedule on Garmin)

| Tool | Purpose |
|------|---------|
| `create_base_workout` | Easy Z2 aerobic |
| `create_recovery_workout` | Z1 recovery |
| `create_long_run_workout` | Long easy |
| `create_threshold_workout` | Z4 intervals |
| `create_sprint_workout` | Z5 sprints |
| `create_hill_repeats_workout` | Z5 hill sprints |
| `create_weighted_pack_workout` | Loaded pack / ruck |
| `combine_workout_templates` | Multi-segment workout |
| `workout` | Low-level custom steps |
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

- `profile`, `race_predictions`, `events`
- **`training_plan`** — week rows (past, current, upcoming): actuals, targets, load, weather
- **`coaching_brief`** — `narrative`, `assessment`, `next_week_proposal`
- `window`, optional `activities`

Coaching rules live in `coaching_brief.py` and `training_plan.py` (not a separate prompt tool).

## REST (n8n)

- `GET /coaching-brief` — primary
- `GET /weekly-report` — same handler (legacy path)
- `GET /health`

## Odysseus skills

- `/garmin-week-review` — `get_coaching_brief` once, narrate `coaching_brief`
- `/garmin-profile` — `get_profile`, `get_events`, `get_race_predictions`
