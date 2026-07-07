# Requirement Implementation — Reference

## Subagent types

| Type | Use for |
|------|---------|
| `explore` | Read-only codebase discovery before implementation |
| `generalPurpose` | Feature implementation, docs, compose changes |
| `bugbot` | PR / branch diff review (`readonly: true`) |

## Bugbot invocation

```text
Full Repository Path: /workspace
Diff: branch changes
```

Use `uncommitted changes` only when reviewing dirty working tree.

Use `natural language` + `Change Description` only if diff computation fails (last resort).

### Finding table format

| Severity | Location (file:line) | Finding |
|----------|----------------------|---------|
| high | path/to/file.py:42 | One-line description |

## Example subagent prompt (single feature)

```text
You are implementing <feature> in ai-home-lab at /workspace.

Branch: cursor/add-foo-mcp-d886 (already checked out)

Task:
- Add foo-mcp service to src/mcp-servers/docker-compose.yml
- Document env vars in .env.example

Context:
- Mirror garmin-mcp compose patterns (edge + mcp-internal networks)
- See docs/DESIGN.md §foo

Do NOT modify:
- src/mcp-servers/garmin-mcp/*

When done:
- Run: python3 -m pytest src/tests/test_garmin_mcp/ -q (if Garmin untouched, skip)
- Commit with clear message
- Do not push

Return: files changed, decisions, manual user steps
```

## Example: parallel dispatch

User request: "Add Actual Budget MCP and remove Garmin workout prescriptions"

1. `explore` agent — map MCP patterns and affected files
2. Branch `cursor/actual-budget-garmin-coaching-d886`
3. Two `generalPurpose` agents in parallel:
   - Agent A: actual-mcp compose + env + docs
   - Agent B: coaching_brief prescription removal + tests + skill docs
4. Parent integrates, tests, PR, Bugbot loop, merge

## PR body template

```markdown
## Summary
- <slice 1>
- <slice 2>

## Test plan
- [x] <command> — N passed

## Manual follow-up (user)
- <Odysseus / .env / Tailscale steps>
```

## Bugbot fix loop exit criteria

- Bugbot: "found no bugs"
- All relevant tests pass
- No uncommitted changes on feature branch
