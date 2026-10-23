# Version log

Change record for the **governed files**: the docs and the contracts. Every change to one of them
gets an entry here, in the same commit. A `pre-commit` hook enforces it.

Why: three people work with separate Claude Code sessions that cannot see each other. This file is
how a session finds out that a design or contract moved since it last looked.

**Doc set version: `v0.4.0`**
**Design status:** HLD draft · LLDs approved: Match Simulation, Data Ingestion, Performance Metrics, Tactical Intelligence, Insight Generation

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
