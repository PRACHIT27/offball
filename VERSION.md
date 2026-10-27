# Version log

Change record for the **governed files**: the docs and the contracts. Every change to one of them
gets an entry here, in the same commit. A `pre-commit` hook enforces it.

Why: three people work with separate Claude Code sessions that cannot see each other. This file is
how a session finds out that a design or contract moved since it last looked.

**Doc set version: `v2.2.1`**
**Design status:** HLD draft · LLDs approved: Match Simulation, Data Ingestion, Performance Metrics, Tactical Intelligence, Insight Generation, Broadcast, Audience, Platform (all eight domains)

---

## Governed files

| File | Why it's governed |
|---|---|
| `README.md` | Team plan: scope, lanes, schedule |
| `CLAUDE.md` | The hub every session loads |
| `COMPETITION.md` | Rules, judging, prizes |
| `docs/design/*.md` | Designs others build against |
| `contracts/*` | Shared schemas (event and frame, cue, MCP tools) |

## Version types

- **MAJOR:** contract change, or architecture change after a design is approved
- **MINOR:** new doc, new requirement, scope change
- **PATCH:** clarification that changes nothing anyone is building against

## Enforcement

Enable once per clone: `git config core.hooksPath .githooks`. Emergency bypass:
`git commit --no-verify`, then log it in the next commit.

---

## Log

## v2.2.1 · 2026-10-27 · Prachit
**Files:** CLAUDE.md, VERSION.md (code: `scripts/deploy_sim.sh`)
**Type:** PATCH
- Match control is live at https://offball-sim.whitemoss-2f18829c.westus2.azurecontainerapps.io (Container App `offball-sim`, identity `id-sim` with Event Hubs Data Sender on `raw-events` and `raw-tracking`, AcrPull on the registry). No passcode.
- `deploy_sim.sh` fixes: turns off Git Bash path rewriting (it silently broke the role grants on Windows) and stamps each deploy so Azure always starts a new revision.

## v2.2.0 · 2026-10-26 · Prachit
**Files:** CLAUDE.md, VERSION.md (code: `sim/control/`, `Dockerfile.sim`, `scripts/deploy_sim.sh`, `tests/sim/test_control.py`, pyproject.toml)
**Type:** MINOR
- Match control: a web page with a Play button that generates (or reuses) a match and streams both feeds into the raw hubs, with live status (preparing, live, half-time, full time; match minute; messages sent) and Stop. One match at a time; optional passcode (`CONTROL_PASSCODE`). This is the Platform design's "run live" button.
- Hosting: Container App `offball-sim` in `offball-env`, external ingress, one warm replica, managed identity `id-sim` (Event Hubs Data Sender on `raw-events` and `raw-tracking` only). `scripts/deploy_sim.sh` creates the identity and roles if missing.
- **Action required:** someone with `az login` on `offball-rg` runs `scripts/deploy_sim.sh` (it creates `id-sim` and the Container App). Lane 3 can link to the page as a separate tab.

## v2.1.0 · 2026-10-26 · Prachit
**Files:** CLAUDE.md, VERSION.md (code: `sim/`, `tests/sim/`, pyproject.toml)
**Type:** MINOR
- Match Simulation built in `sim/`: three fictional clubs with managers (identity, reaction style, risk) and generated squads with abilities and careers; tactics in three layers (identity → match plan → live) that players actually play (line height, offside trap, pressing, compactness, style, tempo, formation); reactions to red cards, leading late and trailing late; six storylines (`red_card`, `comeback`, `switch`, `late_drama`, `press_fade`, `storm`) plus `random --seed N`, which invents a different match story for every seed; answer key with every tactic change and true player stats. CLAUDE.md gains a "Lane 1: Match Simulation" section with the commands.
- Feeds reuse `tests/fixturegen/` writers, mess rules and streamer, so they follow ingestion §13. Checked: ingestion recovers ≥ 99% of events with no dead letters and aligns the clock within 80 ms.
- Realism on the red-card match: ~10 km per outfield player, top speed ~9 m/s, ~30 sprints, 550–700 passes per team at 80–86%, 8–15 shots; Northgate's line drops ~12 m after the 70' red card.
- Deviations from the simulation LLD: no offside events (ingestion has no offside type; the trap still shows in positions); foul and card reasons are sent as feed A qualifiers 301–315, which ingestion currently ignores; storylines with scripted goals get exactly those goals (no natural ones), and storylines with a scripted red card have no random red cards, so scripted scores hold; frames_truth.npz adds possession per frame.
- **Action required:** Data Ingestion maps qualifiers 301–315 to clean `qualifiers` if the Fair Play/referee explanations are wanted. Lanes 2 and 3 can generate matches locally with `python -m sim generate`.

## v2.0.0 · 2026-10-26 · Kanika
**Files:** contracts/README.md (new), contracts/ingestion/*.schema.json (new), CLAUDE.md, VERSION.md
**Type:** MAJOR
- **Proposed** Data Ingestion contract v1.0.0 in `contracts/ingestion/`: clean event, clean frame batch, pre-match info, and the merge outputs (`event.upsert`, `event.delete`, `frames`, `prematch` and the notices). JSON Schema generated from the Pydantic models (`python -m engine.contracts`); a test fails if they drift.
- `contracts/README.md` lists the rules consumers can rely on (clock, pitch, corrections, release order, gap fill) and every notice's `details`.
- Data Ingestion is merged to `main` (PR #2). The engine now uses the async Event Hubs client.
- **Action required:** Lanes 2 and 3 review `contracts/README.md` and agree or ask for changes; until then it is a proposal. The performance-metrics branch merges `main` (expect a conflict in `engine/service.py`).

## v1.1.1 · 2026-10-26 · Kanika
**Files:** CLAUDE.md, VERSION.md
**Type:** PATCH
- Lane 1 section: full Azure resource list (identities, registry, engine app, extra containers), deploy / stop / start / replay commands, where engine logs are, and the before-the-demo always-ready step. The Python 3.12 open item is closed.

## v1.1.0 · 2026-10-26 · Kanika
**Files:** CLAUDE.md, VERSION.md, .githooks/pre-commit (now executable)
**Type:** MINOR
- Data Ingestion local mode is built (`ingest/`, `engine/merge/`, `engine/local.py`); CLAUDE.md gains the setup (uv) and local-mode commands.
- Build decisions on top of the ingestion design: feed A counts as stopped after 60 s of silence (feed B 3 s, as designed), because feed A is naturally quiet for 20–45 s after goals and stoppages; feed health is only judged while the ball is in play; feed A events wait up to 10 s for the first clock anchor at the start of a match; gap start and end notices are sent together when frames resume.
- Clean format additions not yet in `contracts/`: `details` (conditions, stoppage), `timings` (per-stage timestamps), frame numbers count from each period's start, and the clean event `type` list in ingestion §13.1.
- The pre-commit hook was not executable, so git skipped it for everyone; it is now.
- **Action required:** run `git config core.hooksPath .githooks` once per clone if you haven't.

## v1.0.0 · 2026-10-25 · Kanika
**Files:** CLAUDE.md, docs/design/lld-data-ingestion.md, VERSION.md
**Type:** MAJOR
- CLAUDE.md gains a "Lane 1: Data Ingestion" section: build rules, the Azure resources that already exist in `offball-rg` (westus2), and the open Function App runtime item.
- Ingestion design adds §13: raw Feed A and Feed B wire formats, the match clock (period 2 starts at 2,700,000 ms) and the team sheet.
- Architecture deviations for Data Ingestion, recorded here instead of in the designs: **Blob Storage instead of OneLake** (Bronze via Capture to `bronze`, Silver frames as Parquet in `silver-frames`, the fallback the Platform design already allows) and **Pydantic validation only, no Event Hubs Schema Registry** (affects Platform PL-4).
- Clean event and frame schemas stay as Pydantic models in `engine/` until all three agree to publish them in `contracts/`.
- **Action required:** Lane 2 drops Schema Registry from PL-4 for the ingestion hubs. Match Simulation's provider writers follow ingestion §13.

## v0.7.1 · 2026-10-23 · Prachit
**Files:** README.md, docs/design/hld.md, docs/design/diagrams/architecture.svg (new), VERSION.md
**Type:** PATCH
- Detailed high-level architecture diagram (all eight domains, their parts, hubs, Cosmos DB, Platform) added at the top of the README and the high-level design. HLD now links every low-level design.

## v0.7.0 · 2026-10-23 · Prachit
**Files:** docs/design/lld-platform.md (new), CLAUDE.md, VERSION.md
**Type:** MINOR
- New: Platform design with overview diagram. East US 2; one instance kept warm through Nov 10; resource list and names; identity and access table (only `id-eval` reads answer keys); Fabric dashboard tiles with fallback; CI/CD workflows including the results comment; Codespaces and local mode; recorded runs and rate-limited "run live".
- Open: Azure subscription/budget and Fabric capacity still to be decided.
- **Action required:** Lane 2 starts `infra/` and CI on Thursday per §12.

## v0.6.0 · 2026-10-23 · Prachit
**Files:** docs/design/lld-audience.md (new), docs/design/lld-performance-metrics.md, docs/design/lld-tactical-intelligence.md, CLAUDE.md, VERSION.md
**Type:** MINOR
- New: Audience design with dark layout diagram. Pitch as hero, one caption and one highlight at a time, charts in a side panel, viewer types set the density, side-by-side mode, single-metric mode, Ask the studio, English/Spanish/Hindi, phone layout.
- Performance Metrics adds PM-29 player heatmaps; Tactical Intelligence adds TI-35 team territory heatmaps and TI-36 chart series.
- **Action required:** Lane 1 emits `kind: heatmap` and `kind: series` on `stats`. Lane 3 builds the viewer screen per this design.

## v0.5.0 · 2026-10-23 · Prachit
**Files:** docs/design/lld-broadcast.md (new), CLAUDE.md, VERSION.md
**Type:** MINOR
- New: Broadcast design with diagram. Cue manager owns the truth (versions, corrections, pulls, log); each browser schedules for itself on its own match clock; four slots (pitch overlay, caption bar, side panel, timeline) with priority and a 10 s stale rule; producer console watches and pulls; cue feed for external graphics systems.
- **Action required:** Lane 3 builds the browser cue player (clock, inbox, scheduler, filter) and the producer console. Upstream domains use the cue kinds in §6.

## v0.4.0 · 2026-10-23 · Prachit
**Files:** docs/design/lld-insight-generation.md (new), CLAUDE.md, VERSION.md
**Type:** MINOR
- New: Insight Generation design with agent workflow diagram. Coordinator, two tactics agents in parallel, shift explainer, storyteller (4 viewer types × English, Spanish, Hindi), checker with Translator back-check and Content Safety, template fallback, checkpoints. MCP stats server tool list. Ask the studio added.
- **Action required:** Lane 1 Stats API must serve the MCP tools in §6 with an `as_of` cut-off. Lane 3 reads captions keyed `{viewer_type}.{language}`.

## v0.3.0 · 2026-10-22 · Prachit
**Files:** docs/design/lld-tactical-intelligence.md (new), VERSION.md
**Type:** MINOR
- New: Tactical Intelligence design with workflow diagram. Rolling 5-minute windows every 10 s; two levels of output (tactical notes for every change, no AI; triggers for important ones); player position changes count as changes; tunable trigger buffer that caps agent reviews and summarizes bursts; confirm due at 4 minutes; answer-key scoring.
- **Action required:** Lane 2 agents consume trigger types `crux`, `external`, `check_in`, `confirm_due`, `shift`, `summary` with the evidence pack in §7. Lane 3 renders window snapshots and tactical notes from `stats`.

## v0.2.0 · 2026-10-22 · Prachit
**Files:** docs/design/lld-data-ingestion.md (new), docs/design/lld-performance-metrics.md (new), docs/design/hld.md, docs/design/lld-match-simulation.md, README.md, CLAUDE.md, VERSION.md
**Type:** MINOR
- New: Data Ingestion design (Bronze landing via Event Hubs Capture, normalizers, merge stage, mess handling, Silver storage) and Performance Metrics design (calculations, triggering, outputs), each with a diagram.
- Hub `clean` renamed to `normalized`; frames (Bronze and Silver) stored in OneLake.
- Feed A now carries provider xG on every shot; Performance Metrics uses it instead of its own model.
- **No approval step:** every cue, including AI captions, goes on air automatically once checks pass. The producer console can pull (withdraw) any cue.
- **Action required:** Lane 2 drops the approval queue and human-in-the-loop step from the agent workflow; Lane 3 builds the producer console as a live view with a pull button.

## v0.1.1 · 2026-10-22 · Prachit
**Files:** docs/design/lld-match-simulation.md, VERSION.md
**Type:** PATCH
- Fouls, cards and offsides now carry qualifiers (why the call was made), so referee decisions can be explained.
- New match conditions (weather, temperature, pitch, stoppages): part of the truth, sent in feed A, usable as external-factor triggers.
- **Action required:** Lane 1 ingestion must map feed A `typeId: 90` (conditions) and stoppage start/end messages.

## v0.1.0 · 2026-10-21 · Prachit
**Files:** README.md, CLAUDE.md, COMPETITION.md, docs/design/hld.md, docs/design/lld-match-simulation.md
**Type:** MINOR
- Repo created. Team plan, hub, competition summary, high-level design (draft) and the Match
  Simulation low-level design (approved v1.0) with its architecture diagram.
- **Action required:** enable the hook (`git config core.hooksPath .githooks`) and read
  CLAUDE.md before your first session.
