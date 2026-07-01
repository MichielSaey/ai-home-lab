# Odysseus Garmin skills

Import into Odysseus (**Brain → Skills**). We do **not** patch upstream Odysseus.

| Slash command | Purpose |
|---------------|---------|
| `/garmin-week-review` | **`get_coaching_brief`** once — not `get_weekly_report` / `get_coach_prompt` |
| `/garmin-profile` | Profile, events, race predictions only |

See [garmin-mcp-tools.md](../garmin-mcp-tools.md).

## Usage

1. **Agent mode**
2. **Settings → MCP** — Garmin server connected; **`get_coaching_brief` enabled**
3. Invoke: `/garmin-week-review review my past week`
4. Disable unrelated tool groups (documents, skills) if the model calls wrong tools
5. LiteLLM: `drop_params`; no `reasoning_effort` with tools

### If the model says "Garmin tool isn't available"

The skill text is not enough — Odysseus must expose MCP tools on that turn. Check
MCP connection, enable `get_coaching_brief` in the per-server tool list, and
re-import this skill after updates. `requires_toolsets: garmin-mcp` in skill YAML
does not wire MCP automatically (Odysseus limitation).
