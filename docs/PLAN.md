# AI Home Lab — Execution Plan

Checklists, milestones, and GitHub issues. Architecture: [DESIGN.md](./DESIGN.md). Setup: [README.md](../README.md).

<<<<<<< HEAD
=======
**Assignee:** `agent` = repo/code work (hand to a coding agent). `user` = Odysseus admin, phone, Tailscale, or research you do locally.

>>>>>>> refs/remotes/Y/master
---

## Status

| Area | State |
|------|-------|
| Odysseus + compose | Implemented |
| garmin-mcp core tools | Implemented |
| Chainlit `agent_hub` | Removed |
| `garmin_trainer` | Retiring (A.6) |
| ntfy | Bundled; mobile setup open (Track D) |
| n8n, Proton bridge, actual-mcp | Planned |
| epub2audiobook | Implemented; #1 #2 open |
<<<<<<< HEAD
=======
| Garmin coach Phase 2 | Research only (Track B.2) |
>>>>>>> refs/remotes/Y/master

---

## Execution tracks

```mermaid
flowchart TB
  subgraph track_a [Track A Platform]
    A1[Odysseus stack]
    A2[Wire garmin-mcp]
    A3[Retire legacy agents]
  end
<<<<<<< HEAD
  subgraph track_b [Track B Garmin]
    B1[HR zones]
    B2[Coach prompt]
    B3[Profile + review]
    B4[Workouts]
=======
  subgraph track_b1 [Track B Phase 1]
    B1[HR zones]
    B2[Coach prompt]
    B3[Profile + review]
    B4[Workouts + nutrition]
    B5[Health + REST]
  end
  subgraph track_b2 [Track B Phase 2]
    B2R[Research spike]
>>>>>>> refs/remotes/Y/master
  end
  subgraph track_c [Track C epub]
    C1[Voices]
    C2[Tables/graphs]
  end
  subgraph track_d [Track D Alerts]
    D1[ntfy setup]
    D2[notify helper]
  end
  subgraph track_e [Track E n8n]
    E1[Compose]
    E2[Workflows]
  end
  subgraph track_f [Track F Paperless]
    F1[Proton bridge]
    F2[Ingest workflow]
  end
  subgraph track_g [Track G Finance]
    G0[SPIKE]
    G1[Sync alerts]
  end
<<<<<<< HEAD
  A1 --> A2 --> B1 --> B2 --> B3
  B3 --> A3
=======
  A1 --> A2 --> B1 --> B2 --> B3 --> B4
  B4 --> A3
  B4 --> B5
  B2R -.-> B4
>>>>>>> refs/remotes/Y/master
  D1 --> F2
  E1 --> F2
  E1 --> G1
  G0 --> G1
```

---

## Track A — Platform (M1)

<<<<<<< HEAD
| Step | Issue | Work | Done when |
|------|-------|------|-----------|
| A.1 | done | `ensure-odysseus.sh` + `docker compose up` | Odysseus healthy on `:7000` |
| A.2 | new | Odysseus MCP → `http://garmin-mcp:8000/sse` | Tools + weekly report visible |
| A.3 | new | LiteLLM / models in Odysseus | Coach preset replies |
| A.4 | new | `garmin://health` MCP resource | Actionable error messages |
| A.5 | new | Garmin Coach Odysseus preset | Usable without `garmin_trainer` |
| A.6 | new | Remove `src/agents/`, Chainlit/LangGraph | Legacy agents gone |

---

## Track B — Garmin coach (M2)

| Step | Issue | Work | Done when |
|------|-------|------|-----------|
| B.1 | [#3](https://github.com/MichielSaey/ai-home-lab/issues/3) | HR zones in weekly report | Per-activity + weekly rollup |
| B.2 | [#4](https://github.com/MichielSaey/ai-home-lab/issues/4) | `garmin://coach-prompt` (80/20 rules) | Prompt resource in MCP |
| B.3 | new | Profile + variable review tools | goals, preferences, `days_back` |
| B.4 | new | Workout + nutrition tools | Structured create/schedule |
| B.5 | new | REST shim on garmin-mcp | n8n can HTTP fetch report/health |

#4 depends on #3.
=======
| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| A.1 | — | done | `ensure-odysseus.sh` + `docker compose up` | Odysseus healthy on `:7000` |
| A.2 | user | — | Odysseus admin → MCP → `http://garmin-mcp:8000/sse` | Tools + weekly report visible |
| A.3 | user | — | LiteLLM / models in Odysseus Settings | Coach preset replies |
| A.4 | agent | [#9](https://github.com/MichielSaey/ai-home-lab/issues/9) | Garmin Coach preset in `workflows/odysseus/presets/` | Preset file versioned in repo |
| A.5 | user | — | Enable garmin-mcp + Garmin Coach preset in Odysseus | Chat uses MCP tools/resources |
| A.6 | agent | [#7](https://github.com/MichielSaey/ai-home-lab/issues/7) | Remove `src/agents/`, Chainlit/LangGraph | Legacy agents gone |

---

## Track B — Garmin coach

Garmin MCP scope follows [DESIGN §5 garmin-mcp](DESIGN.md#garmin-mcp-implemented): **Phase 1** is execution in this track; **Phase 2** is research only.

### Phase 1 (M2)

| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| B.1 | agent | [#3](https://github.com/MichielSaey/ai-home-lab/issues/3) | HR zone time per activity + weekly rollup | Zones in weekly report |
| B.2 | agent | [#4](https://github.com/MichielSaey/ai-home-lab/issues/4) | `garmin://coach-prompt` (80/20 rules) | Prompt resource in MCP |
| B.3 | agent | [#10](https://github.com/MichielSaey/ai-home-lab/issues/10) | Profile tools + variable review window | goals, injuries, preferences; `days_back` |
| B.4 | agent | [#11](https://github.com/MichielSaey/ai-home-lab/issues/11) | Workout templates + create/schedule tools | Recovery, easy, tempo, threshold, long, sprint; scheduling in template |
| B.5 | agent | [#8](https://github.com/MichielSaey/ai-home-lab/issues/8) | Nutrition matrix (eat/drink cues in workouts) | Matrix tool + workout messages |
| B.6 | agent | [#5](https://github.com/MichielSaey/ai-home-lab/issues/5) | `garmin://health` resource | Structured errors for creds/outage |
| B.7 | agent | [#6](https://github.com/MichielSaey/ai-home-lab/issues/6) | REST shim on garmin-mcp | n8n can `GET /health`, `/weekly-report` |

#4 depends on #3. E.3 (zone alert workflow) depends on B.1 and B.7.

### Phase 2 — research (not in scope yet)

Predictive weekly training from goals + history (distance curve, next-week proposal tool). See [DESIGN §5 Phase 2](DESIGN.md#garmin-mcp-implemented).

| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| B.P2.1 | user | — | Research: predictive model + MCP proposal tool design | Written spike with approach, data needs, validation plan |
| B.P2.2 | agent | — | *(blocked on B.P2.1)* | — |

Do not file implementation issues for Phase 2 until B.P2.1 is complete.
>>>>>>> refs/remotes/Y/master

---

## Track C — epub2audiobook (M3)

<<<<<<< HEAD
| Step | Issue | Work | Done when |
|------|-------|------|-----------|
| C.1 | [#1](https://github.com/MichielSaey/ai-home-lab/issues/1) | Dynamic voices — list, `--voice`, batch random | Voices selectable per run |
| C.2 | [#2](https://github.com/MichielSaey/ai-home-lab/issues/2) | Tables/graphs → ebook reference in TTS | No verbatim table readout |
=======
| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| C.1 | agent | [#1](https://github.com/MichielSaey/ai-home-lab/issues/1) | Dynamic voices — list, `--voice`, batch random | Voices selectable per run |
| C.2 | agent | [#2](https://github.com/MichielSaey/ai-home-lab/issues/2) | Tables/graphs → ebook reference in TTS | No verbatim table readout |
>>>>>>> refs/remotes/Y/master

See [epub2audiobook.md](./epub2audiobook.md).

---

## Track D — Notifications (M4)

<<<<<<< HEAD
| Step | Issue | Work | Done when |
|------|-------|------|-----------|
| D.1 | new | ntfy Tailscale + phone app | Test ping received |
| D.2 | new | `src/shared/notify.py` | Scripts can notify |
| D.3 | new | ntfy action → Odysseus deep link | Tap opens preset |
| D.4 | new | Weekly review → ntfy | Proactive coach ping |
=======
| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| D.1 | user | — | ntfy Tailscale bind + phone app | Test ping received |
| D.2 | agent | [#16](https://github.com/MichielSaey/ai-home-lab/issues/16) | `src/shared/notify.py` | Scripts can notify via `NTFY_*` env |
| D.3 | agent | [#12](https://github.com/MichielSaey/ai-home-lab/issues/12) | ntfy action URLs → Odysseus preset deep links | Tap opens correct preset |
| D.4 | agent | [#15](https://github.com/MichielSaey/ai-home-lab/issues/15) | Weekly Garmin review → ntfy | Proactive coach ping (needs B.1+) |
>>>>>>> refs/remotes/Y/master

---

## Track E — n8n orchestration (M5)

<<<<<<< HEAD
| Step | Issue | Work | Done when |
|------|-------|------|-----------|
| E.1 | new | n8n service in `docker-compose.yml` | n8n running in compose |
| E.2 | new | `workflows/` scaffold + `scripts/n8n-import.sh` | JSON workflows in repo |
| E.3 | new | Garmin zone threshold workflow | Cron → zones → ntfy (needs B.1, B.5) |
| E.4 | new | Pipeline/deploy webhook → ntfy | CI/pipeline alerts on phone |
=======
| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| E.1 | agent | [#17](https://github.com/MichielSaey/ai-home-lab/issues/17) | n8n service in `docker-compose.yml` | n8n running on `edge` network |
| E.2 | agent | [#18](https://github.com/MichielSaey/ai-home-lab/issues/18) | `workflows/` scaffold + `scripts/n8n-import.sh` | JSON workflows in repo |
| E.3 | agent | [#13](https://github.com/MichielSaey/ai-home-lab/issues/13) | Garmin zone threshold workflow | Cron → zones → ntfy (needs B.1, B.7) |
| E.4 | agent | [#14](https://github.com/MichielSaey/ai-home-lab/issues/14) | Pipeline/deploy webhook → ntfy | CI/pipeline alerts on phone |
>>>>>>> refs/remotes/Y/master

---

## Track F — Mail + Paperless (M6)

<<<<<<< HEAD
Depends on Track D and Track E.

| Step | Issue | Work | Done when |
|------|-------|------|-----------|
| F.1 | new | Proton Mail Bridge in compose + n8n IMAP test | n8n reads mail via bridge |
| F.2 | new | Email → Paperless → ntfy workflow | Attachments filed unattended |
=======
Depends on Track D (ntfy) and Track E (n8n).

| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| F.1 | agent | [#23](https://github.com/MichielSaey/ai-home-lab/issues/23) | Proton Mail Bridge container in compose | Bridge on `edge`; IMAP port documented |
| F.2 | agent | [#21](https://github.com/MichielSaey/ai-home-lab/issues/21) | Email → Paperless → ntfy workflow | Attachments filed unattended |

F.1 IMAP credentials: **user** configures in n8n after F.1 is deployed.
>>>>>>> refs/remotes/Y/master

---

## Track G — Actual Budget (M7)

<<<<<<< HEAD
Do not start G.1–G.4 until G.0 is complete.

| Step | Issue | Work | Done when |
|------|-------|------|-----------|
| G.0 | new | SPIKE — answer [DESIGN §4](DESIGN.md#actual-budget-external) Q1–Q10; document REST bridge | Written decisions + bridge URL/auth |
| G.1 | new | n8n sync + uncategorized alert | ntfy → Odysseus finance link |
| G.2 | new | n8n envelope transfer reminders | Threshold → ntfy ping |
| G.3 | new | actual-mcp in compose + Odysseus wire-up | Finance MCP tools in Odysseus |
| G.4 | new | Odysseus finance preset | Interactive clearing via chat |
=======
Do not start G.2–G.4 until G.0 is complete.

| Step | Assignee | Issue | Work | Done when |
|------|----------|-------|------|-----------|
| G.0 | user | — | SPIKE — answer [DESIGN §7 Actual](DESIGN.md#actual-budget) Q1–Q10 | Written decisions + bridge URL/auth |
| G.1 | agent | [#19](https://github.com/MichielSaey/ai-home-lab/issues/19) | n8n sync + uncategorized transaction alert | ntfy with Odysseus finance link |
| G.2 | agent | [#22](https://github.com/MichielSaey/ai-home-lab/issues/22) | n8n envelope transfer reminders | Threshold → ntfy ping |
| G.3 | agent | [#20](https://github.com/MichielSaey/ai-home-lab/issues/20) | actual-mcp service in `docker-compose.yml` | Service on `edge` network |
| G.4 | user | — | Wire actual-mcp in Odysseus admin | Finance MCP tools visible |
| G.5 | user | — | Odysseus finance preset | Interactive clearing via chat |
>>>>>>> refs/remotes/Y/master

---

## Recommended order

```text
<<<<<<< HEAD
Track A (A.1–A.5)     Odysseus + garmin usable
Track D               ntfy first
Track E.1–E.2         n8n scaffold
Track B (#3, #4)      Garmin MCP depth
Track C (#1, #2)      epub (parallel)
Track F               Paperless
Track G.0             Finance SPIKE
Track G.1–G.4         Finance build
Track A.6             Retire legacy agents
=======
Track A (A.1–A.5)       Odysseus + garmin usable (A.2–A.3, A.5 = user)
Track B Phase 1         Garmin MCP depth (#3, #4, then B.3–B.7)
Track D (D.1 user)      ntfy on phone
Track E.1–E.2           n8n scaffold
Track C (#1, #2)        epub (parallel)
Track F                 Paperless
Track G.0 (user)        Finance SPIKE
Track G.1–G.3           Finance automation (agent)
Track G.4–G.5 (user)    Finance Odysseus setup
Track A.6               Retire legacy agents
Track B Phase 2         After B.P2.1 spike only
>>>>>>> refs/remotes/Y/master
```

---

## Definition of done

- [ ] Odysseus is the only agent UI; garmin-mcp is the Garmin surface
<<<<<<< HEAD
- [ ] ntfy alerts with Odysseus deep links (Track D)
- [ ] n8n workflows in repo (Track E)
- [ ] Issues #1–#4 closed
- [ ] Paperless ingest unattended (Track F)
- [ ] Finance SPIKE done before finance automation (Track G)
- [ ] Legacy agent code removed (Track A.6)

---

## New issue templates

Short bodies for rows marked `new` above.

**A.2** — Add garmin-mcp SSE URL in Odysseus admin; verify tools and `garmin://weekly-report`.

**A.3** — Point Odysseus at LiteLLM proxy; verify coach preset responds.

**A.4** — `garmin://health` or `check_connection`; structured errors for outage/missing creds.

**A.5** — Garmin Coach preset; enable garmin-mcp tools/resources.

**A.6** — Remove `src/agents/`, Chainlit deps, `.chainlit/` after preset validated.

**B.3** — `get_training_profile` / `set_training_profile`; `days_back` / `get_review_since`.

**B.4** — Workout templates + `create_workout` / `schedule_workout` + nutrition matrix.

**B.5** — `GET /health`, `GET /weekly-report` HTTP routes for n8n.

**D.1–D.3** — ntfy Tailscale, `notify.py`, deep links to Odysseus presets.

**E.1–E.2** — n8n in compose; `workflows/` + import script.

**F.1–F.2** — Proton bridge container; Paperless ingest workflow.

**G.0** — Answer DESIGN Actual Q1–Q10 before any finance automation code.

**G.3–G.4** — actual-mcp service; finance preset for interactive clearing only.
=======
- [ ] Garmin coach Phase 1 complete (B.1–B.7); Phase 2 spike written (B.P2.1)
- [ ] ntfy alerts with Odysseus deep links (Track D)
- [ ] n8n workflows in repo (Track E)
- [ ] All agent issues closed (#1–#23 except user-only steps)
- [ ] Paperless ingest unattended (Track F)
- [ ] Finance SPIKE done before finance automation (G.0)
- [ ] Legacy agent code removed (A.6)
>>>>>>> refs/remotes/Y/master
