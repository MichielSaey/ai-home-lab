# Garmin MCP — PR integration plan (training plan)

Context from the `experiments/garmin-connect/notebook.ipynb` work (June 2026). Target: implement **`get_training_plan`** in MCP and align open PRs.

## Target architecture

| Piece | Role |
|---|---|
| `get_events` | Next race date (first upcoming event) — **not** duplicated in training plan |
| `get_training_plan` | 4 past weeks + 1 upcoming week: `actuals` + `target` per week |
| `get_weekly_report` | Bundle: profile, race_predictions, events, **training_plan** (replaces `weekly_stats`) |
| `get_weekly_stats` | Low-level rollup — kept for debugging, not in report bundle |
| `garmin://coach-prompt` | Periodization + interpretation rules (from notebook markdown cells) |

### Training plan week object

```json
{
  "week_description": "past_week | current_week | upcoming_week",
  "week_type": "build | recovery | taper_first | taper_final | race",
  "actuals": {
    "distance_km", "easy_pct", "hard_pct",
    "acute_load", "chronic_load", "acwr"
  },
  "target": {
    "distance_km", "easy_pct", "hard_pct"
  }
}
```

Week type is **calculated** from `week_number` (count forward from oldest week in lookback) + `weeks_until_event` (from events list). No `plan_start` stored.

---

## Foundation PR

**Branch:** `cursor/garmin-training-plan-mcp-8dfa`

- `training_status.py` — parse `get_training_status`
- `training_plan.py` — `build_training_plan()`
- `get_training_plan` tool
- `get_weekly_report` returns `training_plan` instead of `weekly_stats`

**Merge this first** before rebasing feature PRs.

---

## Open PR alignment

| PR | Branch | Action after foundation merge |
|---|---|---|
| **#31** | `cursor/garmin-connect-notebook-8dfa` | Keep as **prototype/reference**. Notebook matches MCP logic; no server changes needed. |
| **#25** | `cursor/rollable-weekly-report-4680` | Rebase on foundation. In `get_report()`, replace `weekly_stats` with `training_plan`. Keep `window` params. |
| **#27** | `cursor/garmin-coach-prompt-d871` | Rebase on foundation. Expand `coach_prompt.md` with periodization + training plan interpretation from notebook markdown cells. Agent reads `training_plan` from report. |
| **#26** | `cursor/issue-11-workout-templates-d820` | Rebase on foundation. Orthogonal — workout tools only. Resolve `server.py` conflicts by keeping both workout + training_plan sections. |
| **#29** | `cursor/issue-8-nutrition-matrix-8335` | Rebase on #26 + foundation. Orthogonal — nutrition cues on workouts. |
| **#30** | `cursor/issue-5-garmin-health-resource-8335` | Rebase on foundation. Add `training_plan` to health check optional field or keep health lightweight. |
| **#28** | `cursor/issue-6-garmin-rest-shim-8335` | Rebase on foundation + #30. Add `GET /training-plan?weeks=4` alongside `/weekly-report`. |

### Suggested merge order

```
foundation (#32) → #30 health → #25 report window → #27 coach prompt
                → #26 workouts → #29 nutrition → #28 REST shim
#31 notebook (parallel, reference only)
```

### Conflict hotspot

All PRs touch `mcp-servers/garmin-mcp/server.py`. Prefer extracting logic into modules (`training_plan.py`, `workout_builder.py`, `errors.py`) so `server.py` stays thin registrations.

---

## Agent system prompt sources

Copy from notebook markdown cells:

1. Training load — coach reference (ACWR, acute/chronic)
2. Training periodization — coach reference (week types, volume rules)
3. How to interpret the training plan

These belong in `garmin://coach-prompt` (PR #27), not in the training plan JSON.
