# Version log

Change record for the **governed files**: the docs and the contracts. Every change to one of them
gets an entry here, in the same commit. A `pre-commit` hook enforces it.

Why: three people work with separate Claude Code sessions that cannot see each other. This file is
how a session finds out that a design or contract moved since it last looked.

**Doc set version: `v2.11.0`**
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

## v2.11.0 · 2026-10-27 · Prachit
**Files:** VERSION.md (code: `sim/engine.py`, `scripts/results.py`, replays, results)
**Type:** MINOR
- Simulator, round two:
  - **Defence drops with the ball:** out of possession, the back line stays at least 10 m goal-side of the ball. Before, it never dropped below about 30 m from goal, so attackers ended up behind it.
  - **Offside line:** attackers line up with the opponent's last outfield defender, and an offside attacker jogs back at 5 m/s instead of 2–3 m/s. Moments with someone more than 2 m offside fell from about 65% to about 35%; most of what's left is players recovering after an attack.
  - **Keepers** come off their line when their team has the ball (median 15 m, at most 20 m; was at most 12 m).
  - **Shots:** a slightly higher bar to shoot (18–34 per match).
- Full matches: about 20% of passes backward, 7–8% straight return passes, 3.6–3.8 passes per move.
- Scores, scripted cards and every tactic change still land at the same minutes. Replays, captions, metrics views and results are rebuilt in the same push.

## v2.10.0 · 2026-10-27 · Prachit
**Files:** VERSION.md (code: `sim/engine.py`, `sim/clubs.py`)
**Type:** MINOR
- More realistic play in the simulator:
  - **Shape:** with the ball, the whole team now stays under the opponent's offside line. Before, midfielders ended up ahead of their own strikers, so most of their passes went backward.
  - **No ping-pong:** a player is less likely to pass straight back to whoever just passed to them (under pressure they still can). Return passes fell from 31% to about 9–16%.
  - Result on the six storylines: about 23–26% of passes go backward (was 59%), sequences average 4–5 passes (was 6.5), 15–23 shots and 13–29 fouls per match.
  - **Cards:** scripted storylines no longer get unscripted red cards, and a booked player isn't booked again unless natural reds are on.
  - **Names:** every player has a unique surname (was 30 surnames for 54 players). Same random draws, so squads and abilities are unchanged.
- Scores, scripted cards and every tactic change land at the same minutes as before, but the matches themselves are new.
- **Action required:**
  - Lane 1: regenerate `local_feeds/` and rerun `scripts/results.py`, since old answer keys don't match new matches.
  - Lane 3: rebuild the replays and metrics views (`scripts/build_replay.py`, `scripts/build_metrics_view.py`).
  - Lane 2: rerun the agent captions on the new replays (`python -m insights.local … --agents --replay …`).
  - Platform: redeploy match control (`scripts/deploy_sim.sh`).

## v2.9.0 · 2026-10-27 · Kanika
**Files:** CLAUDE.md, VERSION.md (code: `insights/service.py`, `insights/live.html`, `Dockerfile.insights`, `scripts/deploy_insights.sh`)
**Type:** MINOR
- Live Insight Generation on Azure. Container App `offball-insights` (identity `id-insights`) turns triggers into checked captions while a match plays, and serves them on a live captions page (4 viewer types × EN, ES, HI) and at `/api/insights`.
- New Azure resources:
  - Identity `id-insights` with Event Hubs Data Receiver on `triggers` and `stats`, Cosmos Built-in Data Reader on `events`, Cognitive Services OpenAI User and Cognitive Services User on `offball-ai-kr2610`, and AcrPull.
  - Consumer group `insights` on `stats`.
  - The Container App: 1 replica, external ingress.
- Tested on a live random match (`r2711`, 10×): captions arrive about 8 s (expect) to 20 s after each trigger.
- Not yet: insights are kept in memory (a restart loses them; Cosmos `insights` is the next step); the viewer screen's live mode doesn't read them yet.
- **Action required:** Lane 3 can show live captions from `GET /api/insights?match_id=…&since=…` (JSON, newest via `since`). Stop the app when not demoing: `az containerapp` is unavailable on Python 3.14 CLIs, so use the ARM `stop` call as in `scripts/engine.sh`.

## v2.8.0 · 2026-10-27 · Kanika
**Files:** CLAUDE.md, VERSION.md (code: `insights/safety.py`, `insights/checker.py`, `insights/workflow.py`, `web/public/replays/m00{1,2,3}.json`)
**Type:** MINOR
- Checker rules 3 and 5 (IG-23, IG-24), keyless on `offball-ai-kr2610`:
  - **Translator back-check:** Spanish and Hindi captions are translated back to English and checked like English ones.
  - **Content Safety:** screens every caption; any severity above 0 takes the caption off air.
  - **Failure handling:** a flagged caption goes back to the storyteller with the reason. If a service is down, the captions it couldn't check fall back to their templates.
- Grounding fixes:
  - IDs (`w-NGU-2-5030-5530`) no longer count as allowed numbers.
  - A number in a fact's name counts (`xg_per_10_minutes` allows 10).
  - A colon no longer separates a claim from its numbers.
  - Rounding to the boundary passes (8.15 → 8.2).
- All three replays (`m001` red card, `m002` comeback, `m003` switch) carry agent captions.
- The `gpt-5-mini` deployment (100K TPM) rate-limits two matches at once: run matches one at a time.
- **Action required:** Lane 3 (viewer): the replays now carry `insights`. Rebuilding a replay with `scripts/build_replay.py` drops them; rerun `python -m insights.local … --agents --replay …` after it.

## v2.7.0 · 2026-10-27 · Kanika
**Files:** CLAUDE.md, VERSION.md (code: `insights/`, `mcp_stats/`, `tests/insights/`, `web/public/replays/m001.json`)
**Type:** MINOR
- Insight Generation steps 2–4: the code checker (LLD §8 rules 1, 2 and 4, plus units, pitch coordinates, abbreviations, "expect" targets and word limits), the MCP stats server (`mcp_stats/`, 10 tools over Tactical Intelligence's windows and the clean events, `as_of` cut-off) and the agent team on Microsoft Agent Framework with gpt-5-mini.
- Red-card match: every insight comes from the agents (template fallback only per caption); expect insights take 5–8 s and the others a median of about 15 s, inside the 8 s / 20 s deadlines.
- Deviations from the Insight Generation design:
  - **Expect runs without the tactics agents.** They take 6–8 s and can't fit the 8 s deadline; the trigger already carries the team's current state, and the tactics agents check the prediction at confirm-due time.
  - **The coordinator and checker are code only** (no model). The storyteller writes one language per call, three in parallel.
  - **Spanish word limits are 20% longer** than the English ones; Hindi has none.
  - **"Normal style" is the team's own minutes 5–15 of this match**, as in Tactical Intelligence.
  - **No `get_player_stats` yet:** Performance Metrics data isn't in the Stats API.
- The style dial runs from 0 (patient, short passing) to 100 (direct, long balls).
- Not built yet: Translator back-check, Content Safety, Cosmos storage of insights, the live `triggers` listener, checkpoints and recovery, recaps, Ask the studio.

## v2.6.0 · 2026-10-27 · Kanika
**Files:** CLAUDE.md, VERSION.md (code: `insights/`, `tests/insights/`, `web/src/`, `web/public/replays/m001.json`, pyproject.toml)
**Type:** MINOR
- Insight Generation started (Kanika owns it). Step 1: an insight per trigger with 12 template captions (4 viewer types × en, es, hi), written only from the trigger's facts (IG-3, IG-22, IG-25, IG-31). Kinds: expect (crux), confirmed / retracted (confirm due, using Tactical Intelligence's change thresholds), shift, summary, check-in, external.
- The viewer screen shows insight captions for the chosen viewer type, and gains an EN / ES / HI switch. Captions are marked `AI` (agent) or `auto` (template). Insight captions replace the screen's own shift captions for the same trigger. `m001.json` carries the insights.
- New Azure: AI Services `offball-ai-kr2610` (Sweden Central, keys off) with `gpt-5-mini`; details in CLAUDE.md.
- `tests/engine/test_local_mode.py` now also guards `insights/` against reading the answer key. That test already failed on `main` because `engine/tactics/local.py` has `--answer-key`.
- **Action required:** Tactical Intelligence moves answer-key scoring out of `engine/tactics/local.py` (for example into `tests/`) or narrows the guard. Lane 3: `scripts/build_replay.py` rewrites a replay without insights; run `python -m insights.local … --replay` after it.

## v2.5.1 · 2026-10-27 · Archit
**Files:** README.md, CLAUDE.md, VERSION.md (code: `web/public/staticwebapp.config.json`, `.github/workflows/web.yml`, `web/README.md`)
**Type:** PATCH
- The viewer screen is online at https://jolly-cliff-0ccede51e.4.azurestaticapps.net: Static Web App `offball-web` (Free, westus2) in `offball-rg`, serving the three recorded matches. Share links such as `?match=m001&t=4300&type=analyst` open a moment.
- README links the live screen; CLAUDE.md gains "Lane 3: Viewer screen" with run, build and deploy commands.
- `.github/workflows/web.yml` builds the screen on every PR and deploys on pushes to `main`.
- **Action required:** a repo admin (Prachit) adds the secret `AZURE_STATIC_WEB_APPS_API_TOKEN` once; the command is at the top of the workflow file. Until then, deploy by hand (web/README.md). Whoever changes `web/` (e.g. Insight Generation captions) redeploys after merging.

## v2.5.0 · 2026-10-27 · Archit
**Files:** CLAUDE.md, VERSION.md (code: `engine/metrics/`, `engine/service.py`, `engine/store_azure.py`, `scripts/deploy_engine.sh`)
**Type:** MINOR
- Performance Metrics is built on branch `performance-metrics` (on top of the Data Ingestion work): every Must in its design plus completion vs expected and heatmaps; pressure seconds and fatigue are not built. Local mode, the Azure path (`stats` hub, Cosmos `metrics`, wired into `engine/service.py`), and truth, delay, restart and Azure-path tests.
- Merged `main` up to v2.4.0. Metrics consumes the proposed `contracts/ingestion` v1.0.0 as is, so Performance Metrics agrees to it.
- `engine/service.py` combines the two router hooks: Performance Metrics (`METRICS_ENABLED=1`) and Tactical Intelligence (`TACTICS_ENABLED=1`) both get every merge output, and a failure in one doesn't stop the other. Both are off by default; `scripts/deploy_engine.sh` passes `METRICS_ENABLED` like `TACTICS_ENABLED`.
- Metrics shares the `stats` hub with Tactical Intelligence. The kinds don't overlap (metrics: `positions`, `player_totals`, `heatmap`, `pass`, `shot`, `xg`; tactics: `window`, `series`, `territory`, `note`). Metrics messages also carry the property `type` (`stats` or `cue`).
- Tactical Intelligence computes its own pressing and pitch value from frames and events, so `PressureSample` and `PassValues` currently have no listener. They stay available.
- CLAUDE.md gains a "Lane 1: Performance Metrics" section. Message shapes and per-teammate notes are in `engine/metrics/README.md`; they are not yet in `contracts/`.
- Decisions beyond the design: movement over 12 m/s is a tracking jump, not running; the best-option arrow shows below a 0.4 decision score; raw positions travel on `stats` as `positions`; number-only cues travel on `stats` with property `type=cue`.
- **Action required:**
  - Tactical Intelligence: nothing required; `PressureSample` / `PassValues` are there if you want metrics' carrier pressure instead of your own.
  - Insight Generation: the Stats API reads Cosmos `metrics` (totals are cumulative; keep the highest event version).
  - Broadcast / Audience: consume `stats` by the `type` and `kind` properties; the shapes are in the README.
  - Platform / Data Ingestion: the `stats` hub and `id-engine`'s Data Sender on it now exist (v2.4.0). Still needed before `METRICS_ENABLED=1`: Cosmos container `metrics` (partition `/match_id`) and `id-engine`'s Cosmos role on it. Optional: consumer group `cues` on `stats` for the cue manager. Commands in the README; nothing has been created.
  - Match Simulation: send `provider_xg` on every shot.

## v2.4.0 · 2026-10-27 · Prachit
**Files:** CLAUDE.md, VERSION.md (code: `engine/tactics/`, `engine/service.py`, `scripts/deploy_engine.sh`)
**Type:** MINOR
- Tactical Intelligence runs on the live engine when `TACTICS_ENABLED=1`: it plugs into the engine's router hook and publishes windows, series, territory and notes to the new `stats` hub and triggers to the new `triggers` hub (partition key `match_id`). If a restart missed the pre-match info it reads it from Cosmos.
- New Azure resources: hubs `stats` (consumer groups `bridge`, `fabric`) and `triggers` (`agents`, `fabric`), 2 partitions, 24 h retention; `id-engine` has Event Hubs Data Sender on both.
- Tuned defaults (scored on six storylines against the answer key): pressing must change 50% and by 1.5 presses/min; a change is confirmed after 5 minutes (tentative still at 2). Keeps every catch the old settings had; false alarms down about a third on Red Card and half on Switch.
- **Action required:** Lane 2 reads triggers from `triggers` with consumer group `agents`. Lane 3 reads `stats` with consumer group `bridge`. The Performance Metrics branch will conflict in `engine/service.py` (both use the router hook); combine the two routers there.

## v2.3.0 · 2026-10-27 · Prachit
**Files:** CLAUDE.md, VERSION.md (code: `engine/tactics/`, `tests/tactics/`)
**Type:** MINOR
- Tactical Intelligence built (local mode). Every 10 s of match time, each team's last 5 minutes: line height, offside traps, compactness, formation in and out of possession, pressing (per minute, size, triggers, PPDA), recovery time, style dial, control vs. chaos, tempo, passing network, chance routes, player positions; territory heatmaps every 60 s; chart series every window.
- Change detector with tentative (2 min) and confirmed (4 min) notes, anchored to the level before the change; promoter; trigger maker (goals, cards, subs, conditions, long stoppages, 85', check-ins at 15/30/45/60/75/90, confirm due 4 min after a crux with did-it-work); tunable trigger buffer with summaries; answer-key scoring.
- Red-card storyline: catches the half-time switch to a back three, Riverside dropping deeper when leading, and Northgate's line dropping ~8–12 m after the 70' red card (confirm due at 74'). Switch storyline: 4 of 4. Press Fade: 2 of 9, and false alarms are still high (teams also react without a scripted change); thresholds need tuning.
- Deviations from the TI LLD: settings are JSON, not YAML; possession is inferred from on-ball events (frames carry none); the "normal style" baseline is the team's own 5–15 minute play in this match, not club history, because measured and scripted scales differ; triggers also carry `reason` and `play_ms`.
- Not yet: Azure sinks (`stats`, `triggers` hubs) and wiring into the deployed engine's router.
- **Action required:** Lane 2 can build agents against `local_out/<match>/tactics/triggers.jsonl` now. Lane 3 can draw windows, series and territory from the same folder.

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
