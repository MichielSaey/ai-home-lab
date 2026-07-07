---
name: requirement-implementation
description: End-to-end workflow for implementing user requirements in this repo — analyze scope, dispatch implementation subagent(s), open a PR, run Bugbot review, fix findings, and merge to main. Use when the user asks to implement a feature, gestured requirement, track step, or says "handle it like the others".
---

# Requirement Implementation

Standard delivery loop for agent-assigned work in **ai-home-lab**.

## When to use

- User gives one or more concrete requirements to implement
- User references a PLAN.md track step or GitHub issue
- User says "dispatch a subagent", "handle it the same way", or similar gesture requests
- Multiple independent features can be parallelized across subagents

## Workflow

```
Task Progress:
- [ ] 1. Analyze requirement
- [ ] 2. Create feature branch
- [ ] 3. Dispatch subagent(s) to implement
- [ ] 4. Verify (tests), commit, push
- [ ] 5. Open or update PR
- [ ] 6. Run /review-bugbot
- [ ] 7. Fix findings; re-run Bugbot until clean
- [ ] 8. Merge to main
```

### 1. Analyze requirement

Before writing code:

1. Read relevant docs: `docs/DESIGN.md`, `docs/PLAN.md`, README, existing MCP patterns.
2. Search the codebase for related implementations and conventions.
3. Split work into **independent slices** (one subagent per slice when possible).
4. Note manual follow-up steps for the user (Odysseus admin, `.env`, Tailscale).

Do not estimate calendar time. Describe technical scope instead: components touched, risks, dependencies.

### 2. Create feature branch

Branch from `main`:

```bash
git checkout main && git pull origin main
git checkout -b cursor/<descriptive-name>-d886
```

Rules:

- Prefix: `cursor/`
- Suffix: `-d886` (cloud agent convention)
- Lowercase, hyphenated descriptive name

One branch per PR unless the user explicitly wants separate PRs per slice.

### 3. Dispatch subagent(s)

Launch `generalPurpose` subagents (or domain-specific types when available) with:

- Absolute repo path: `/workspace`
- Target branch name (already checked out)
- Concrete file paths, patterns, and **do-not-touch** boundaries
- Test commands to run before commit
- Instruction: commit locally, do **not** push (parent agent owns PR)

**Parallelize** when slices are independent — but only one subagent writes/commits at a time on the shared branch. Either:

- Launch parallel agents for **read-only analysis**, then one implementation agent; or
- Launch parallel implementation agents on **separate branches**, then integrate in the parent; or
- Run implementation subagents **sequentially** on the same branch (safest default).

Never have two write-capable subagents commit concurrently on `/workspace`.

Each subagent prompt should include:

```text
Task: <what to build>
Branch: cursor/<name>-d886
Context: <docs, patterns, constraints>
Files to change: <paths>
Do NOT modify: <paths>
When done: run <test command>, commit with clear message, do not push
Return: summary of changes, decisions, manual user steps
```

### 4. Verify, commit, push

Parent agent after subagents return:

1. Review diffs for scope creep and convention drift.
2. Run tests (`python3 -m pytest src/tests/…` for Garmin MCP; project-specific commands otherwise).
3. Fix integration issues between parallel slices.
4. Stage any parent-agent edits, commit only when there are changes, then push:

```bash
git add -A
git diff --cached --quiet || git commit -m "<clear message>"
git push -u origin cursor/<descriptive-name>-d886
```

If subagents already committed, skip the empty commit and push their commits directly.

Commit and push **before** Bugbot review when iterating on fixes.

### 5. Open or update PR

Use PR management tool or `gh pr create`:

- `base_branch`: `main`
- Title: concise summary of all slices
- Body: per-slice summary, test plan checklist, manual user follow-up

Default to draft PR only when work is intentionally incomplete.

### 6. Run /review-bugbot

Follow the `review-bugbot` command skill exactly:

- Launch one `bugbot` subagent, `readonly: true`, `description: "Bugbot"`
- Default `Diff: branch changes` against `main`
- Summarize findings in a table: Severity | Location | Finding

### 7. Fix findings

For each Bugbot finding (highest severity first):

1. Implement a focused fix — minimal diff, match repo conventions.
2. Run affected tests.
3. Commit and push.
4. Re-run `/review-bugbot`.

Stop when Bugbot reports **no bugs** or only findings the user explicitly accepts.

Do **not** merge with open high-severity findings unless the user overrides.

### 8. Merge to main

**Prefer PR merge** when PR tooling is available:

1. Ensure Bugbot is clean and tests pass on the feature branch.
2. Merge the PR into `main` via PR management tool or `gh pr merge`.

**Direct merge** only when PR creation is blocked by repo settings:

```bash
git checkout main && git pull origin main
git merge cursor/<descriptive-name>-d886
git push origin main
```

Do not push directly to `main` when an open PR exists for the same branch — merge through the PR instead.

## Repo conventions (quick reference)

| Area | Pattern |
|------|---------|
| MCP servers | `src/mcp-servers/<name>/`, register in `src/mcp-servers/docker-compose.yml` |
| Env vars | Root `.env.example` only |
| Garmin tests | `python3 -m pytest src/tests/test_garmin_mcp/ -v` |
| Docs | Update `docs/PLAN.md` status when a track step completes |
| Scope | Smallest correct diff; no drive-by refactors |

## Multi-requirement requests

When the user lists multiple features:

1. Analyze and split into independent subagent tasks.
2. Use one branch and one PR unless they ask for separate PRs.
3. Mention parallel subagent dispatch in the PR body.

## Output to user

Final summary should include:

- What was implemented (per slice)
- Bugbot result (findings fixed, final status)
- Test results
- Merge status
- Manual follow-up for the user (if any)

## Additional resources

- Bugbot prompt template and retry rules: [reference.md](reference.md)
