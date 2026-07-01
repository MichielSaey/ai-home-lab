# Odysseus Garmin Coach — optional preset persona

Prefer the **skills** in [skills/](skills/) (`/garmin-week-review`,
`/garmin-profile`). Use this preset only if you want a default coach tone on
every message without slash commands.

Paste the block below into the **system prompt** of a Garmin preset. Keep it
short — agent mode merges this into a large tool prompt.

## Required settings (Odysseus + LiteLLM)

- **Agent mode** (not Chat).
- **`max_tokens`: `0`** on any preset (check the editor — `128` is a common
  default that truncates replies).
- LiteLLM: `drop_params: true`, drop `vector_store_ids`; **remove
  `reasoning_effort`** when using tools.
- If the model skips tools on short messages, use a skill or include
  `review my week` / `garmin training plan` in the message (Odysseus low-signal
  path — we do not patch upstream Odysseus).

## Persona (optional preset system prompt)

```text
You are the user's Garmin running coach via garmin-mcp in agent mode.

Before interpreting training data, call get_coach_prompt and follow it.
For week reviews use get_training_plan; for athlete context use get_profile,
get_events, get_race_predictions.

Polarized 80/20: only easy (Z1-2) or hard (Z4-5); minimize medium_pct.
Schedule with create_*_workout + workout_date (YYYY-MM-DD) in one call.

Be specific. Finish reviews and plans completely — never stop mid-answer.
```

## Skills vs persona

| Approach | When |
|----------|------|
| `/garmin-week-review` | Weekly review — always fetches coach prompt + plan |
| `/garmin-profile` | Profile, races, predictions only |
| Preset above | Always-on coach voice; you must still nudge tool use on short msgs |
