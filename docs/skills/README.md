# Odysseus Garmin skills

Import these into Odysseus (**Brain → Skills → add/import**) or copy each
`SKILL.md` into your Odysseus skills directory. We do **not** patch Odysseus
itself — it is an upstream service in `services/odysseus`.

| Slash command | Title | Purpose |
|---------------|-------|---------|
| `/garmin-week-review` | Garmin week review | `get_coach_prompt` + `get_training_plan` → coached weekly review |
| `/garmin-profile` | Garmin profile | Profile, events, race predictions |

Replace any long learned names (e.g. `garmin-week-review-from-mcp`) with these
shorter slugs after importing.

## Usage (no Odysseus fork required)

1. **Agent mode** — chat mode does not pass MCP tools.
2. Invoke with a real task, not only `Hey`:
   - `/garmin-week-review review my past week`
   - `/garmin-profile show my races and predictions`
3. If replies are cut off at ~128 tokens or the model will not call tools, add
   explicit words in the same message: `garmin`, `training plan`, or
   `get_training_plan` (Odysseus “low-signal” fast path — upstream behavior).
4. Disable unused built-in tool groups in Settings so garmin-mcp tools win
   tool-RAG.
5. LiteLLM: `drop_params` + strip `vector_store_ids`; **no `reasoning_effort`**
   on gpt-5.4 with tools.

See also [odysseus-coach-persona.md](../odysseus-coach-persona.md) for an
optional short preset system prompt (backup if you prefer a persona over skills).
