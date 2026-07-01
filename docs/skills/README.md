# Odysseus Garmin skills

Import into Odysseus (**Brain → Skills**). We do **not** patch upstream Odysseus.

| Slash command | Purpose |
|---------------|---------|
| `/garmin-week-review` | **`get_coaching_brief`** once — review + proposal |
| `/garmin-profile` | Profile, events, race predictions only |

See [garmin-mcp-tools.md](../garmin-mcp-tools.md).

## Usage

1. **Agent mode**
2. Invoke with a real task: `/garmin-week-review review my past week`
3. Disable unused built-in tool groups so garmin-mcp wins tool-RAG
4. LiteLLM: `drop_params`; no `reasoning_effort` with tools
