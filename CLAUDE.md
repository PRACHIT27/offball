# OffBall: read this first

This file is the hub. Three people build this in parallel with separate Claude Code sessions that
cannot see each other, so everything a session needs to stay consistent lives here or is linked
from here.

## What we're building

> **OffBall sees where every player is, reads the tactics, notices when they change, and explains
> it on screen. Visuals first, a short caption alongside.**

A simulated match streamed as two messy provider feeds, cleaned and merged, turned into stats and
tactics from player positions, explained by a team of agents that predict and then confirm, checked
so no number is invented, on air automatically with a producer override, and personalized per viewer type, club, player
and language.

Inside the Game: Developer Hackathon (Microsoft × Premier League). Deadline **Tue Oct 27, 2026,
11:59 pm PT**. We submit Tuesday afternoon ET.

Stack: Python 3.12 · Azure Event Hubs · Azure Functions · Container Apps · Cosmos DB · Microsoft
Foundry · Microsoft Agent Framework · MCP · Azure AI Services · Fabric · React + TypeScript ·
Web PubSub · azd + Bicep.

## Canonical external references: check these, don't trust our summaries

| Source | URL | Ours that summarises it |
|---|---|---|
| Official rules | https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md | [COMPETITION.md](COMPETITION.md) |
| Rules short link | https://aka.ms/insidethegame/rules | |
| Skilling playlists | https://aka.ms/aisn/hack | [README.md §17](README.md#17-learning-resources) |
| Reactor sessions | https://developer.microsoft.com/en-us/reactor/series/S-1709/ | |

When a question touches rules, eligibility, prizes or submission, fetch the live rules page.

## Doc map

| Doc | What it is |
|---|---|
| [README.md](README.md) | Team plan: rules, scope, lanes, schedule, demo, checklist |
| [COMPETITION.md](COMPETITION.md) | What we are judged against |
| [docs/design/hld.md](docs/design/hld.md) | High-level design: domains, Azure architecture, flows, contracts |
| [docs/design/lld-match-simulation.md](docs/design/lld-match-simulation.md) | Low-level design: Match Simulation (approved) |
| [docs/design/lld-data-ingestion.md](docs/design/lld-data-ingestion.md) | Low-level design: Data Ingestion (approved) |
| [docs/design/lld-performance-metrics.md](docs/design/lld-performance-metrics.md) | Low-level design: Performance Metrics (approved) |
| [docs/design/lld-tactical-intelligence.md](docs/design/lld-tactical-intelligence.md) | Low-level design: Tactical Intelligence (approved) |
| [docs/design/lld-insight-generation.md](docs/design/lld-insight-generation.md) | Low-level design: Insight Generation (approved) |
| [docs/design/lld-broadcast.md](docs/design/lld-broadcast.md) | Low-level design: Broadcast (approved) |
| [docs/design/lld-audience.md](docs/design/lld-audience.md) | Low-level design: Audience (approved) |
| [docs/design/lld-platform.md](docs/design/lld-platform.md) | Low-level design: Platform (approved) |
| `docs/design/lld-*.md` | One low-level design per domain, added as each is approved |
| [contracts/README.md](contracts/README.md) | Shared schemas between lanes; ingestion's clean event and frame (proposed v1.0.0) |
| [VERSION.md](VERSION.md) | Change log for governed files. Read the newest entries before you start |

## Rules that bite

1. **Fictional everything.** No real clubs, players, managers or crests anywhere: code, fixtures,
   captions, screenshots, the video. The rules disqualify third-party trademarks.
2. **Synthetic data only.** No real Premier League data or footage.
3. **Code computes every number. Agents only explain.** No number on screen may originate from a
   model. Every cue carries `evidence` (event and window IDs).
4. **The answer key never reaches the live path.** Only evaluation tests read `answer-keys/`.
5. **Provider formats stop at Data Ingestion.** Everything after it sees only our clean format.
6. **Own your data.** A domain never reads another domain's storage; it asks via message, API or MCP.
7. **No keys in code.** Managed identities everywhere. This repo is public.
8. **Visual first.** Every insight gets a picture on the pitch; the caption only names it.

## Shared conventions

| Item | Rule |
|---|---|
| Clock | `match_clock_ms` + `period` everywhere. Wall-clock time only in `emitted_at` headers |
| Pitch | Metres, 105 × 68, origin at a corner, home attacks toward x = 105 (flip handled at ingest) |
| IDs | Clubs `RIV`, players `RIV-07`, events `e-004512`, windows `w-NGU-60-70`, cues `cue-0193` |
| Corrections | Same ID, higher `version`. Keep the highest |
| Fictional clubs | Riverside Athletic (RIV), Northgate United (NGU), Kestrel Vale (KVA) |

## Lanes

| Lane | Domains | Owner |
|---|---|---|
| 1 · Data engine | Match Simulation, Data Ingestion, Performance Metrics, Tactical Intelligence | _TBD_ |
| 2 · AI and backend | Insight Generation, Platform (infra, CI) | _TBD_ |
| 3 · Experience | Broadcast, Audience, submission | _TBD_ |

## Working agreement

- `git pull`, then read the newest [VERSION.md](VERSION.md) entries, before each session.
- Enable the hook once per clone: `git config core.hooksPath .githooks`.
- Changing a governed file (top-level docs, `docs/design/*.md`, `contracts/`) needs a VERSION.md
  entry in the same commit. The hook blocks it otherwise.
- Contracts change only if all three agree.

## Lane 1: Data Ingestion

Rules for any session building Data Ingestion (`ingest/` normalizers, `engine/` merge stage).

| Rule | Detail |
|---|---|
| Design | Build exactly as [lld-data-ingestion.md](docs/design/lld-data-ingestion.md) specifies, except the two deviations below |
| Deviation: storage | Blob Storage instead of OneLake: Bronze via Capture to `bronze`, Silver frames as Parquet in `silver-frames` |
| Deviation: validation | Validate with Pydantic models only; no Event Hubs Schema Registry |
| Python | 3.12 in `.venv` via uv (`uv venv --python 3.12 .venv && uv pip install --python .venv -e '.[dev]'`); Pydantic; pytest. Homebrew's Python 3.12 can't load `pyexpat` on this Mac |
| Local first | Build local mode (FR-29) first; everything must run from files with no Azure |
| Plain functions | Keep logic in plain functions; Azure Functions and the engine only call them |
| Mess levels | Build the `light` mess level first; `full` last |
| Raw feed formats | Feed A and Feed B wire formats are not in the LLD: propose them and wait for the owner's OK before building |
| Data and secrets | Fictional clubs and players only. Never commit or print secrets from `.env` |
| Azure changes | Ask before creating, changing or deleting any Azure resource |
| Local mode | `python -m tests.fixturegen --out local_feeds/fx01 --mess light`, then `python -m engine.local --feeds local_feeds/fx01/feeds --out local_out --match fx01` |

**Azure resources** (resource group `offball-rg`, region `westus2`; `bash azure-setup.sh` rebuilds all of it):

| Resource | Name |
|---|---|
| Event Hubs namespace (Standard) | `offball-eh-kr2610`: hubs `raw-events`, `raw-tracking` (Capture on → `bronze`), `normalized`; consumer groups `ingest`, `ingest`, `engine` |
| Storage, data (hierarchical namespace) | `offballstkr2610`: containers `bronze`, `silver-frames`, `dead-letter`, `checkpoints`, `teamsheets` |
| Cosmos DB (serverless) | `offball-cosmos-kr2610`: database `offball`, container `events` (partition `/match_id`) |
| Function App (Flex Consumption, Python 3.12) | `offball-ingest-kr2610`: normalizers `normalize_feed_a`, `normalize_feed_b` as `id-ingest`; plan `ASP-offballrg-7469`, storage `offballfnkr2610`, Application Insights `offball-ingest-kr2610` |
| Container Apps | environment `offball-env` (express, no log destination); app `offball-engine` (1 replica) as `id-engine` |
| Container registry | `offballacrkr2610` (image `offball-engine`) |
| Managed identities | `id-ingest`, `id-engine`, least-privilege roles per LLD §10 |

| Task | Command |
|---|---|
| Deploy normalizers | `scripts/build_functionapp.sh && (cd build/functionapp && func azure functionapp publish offball-ingest-kr2610 --python)` |
| Deploy engine (Docker running) | `scripts/deploy_engine.sh` |
| Stop / start engine | `scripts/engine.sh stop` / `scripts/engine.sh start` |
| Replay a fixture into Azure | `python -m tests.fixturegen.stream --feeds local_feeds/fx01/feeds --speed 10` |
| Engine logs | Application Insights `offball-ingest-kr2610`, `cloud_RoleName == "offball-engine"` |

**Before the demo:** turn on one always-ready normalizer instance (off during build to save cost):
`az functionapp scale config always-ready set -g offball-rg -n offball-ingest-kr2610 --settings function:normalize_feed_b=1`.
Afterwards: `az functionapp scale config always-ready delete -g offball-rg -n offball-ingest-kr2610 --setting-names function:normalize_feed_b`.

## Lane 1: Performance Metrics

Rules for any session building Performance Metrics (`engine/metrics/`). Hand-off notes for every
teammate: [engine/metrics/README.md](engine/metrics/README.md).

| Rule | Detail |
|---|---|
| Design | Build as [lld-performance-metrics.md](docs/design/lld-performance-metrics.md) specifies; decisions beyond it are listed in the README's "Decisions and open items" |
| Branch | `performance-metrics` (carries the Data Ingestion work it builds on). Never push to `main` |
| Python | Same `.venv` as Data Ingestion, with Azure extras: `uv pip install --python .venv -e '.[dev,azure]' azure-functions` |
| Local first | `python -m engine.metrics.local --feeds local_feeds/m001/feeds --out local_out --match m001` (any `python -m sim generate` match or fixture) |
| Live | Engine with `METRICS_ENABLED=1` (after the Cosmos `metrics` container exists); deploy with `METRICS_ENABLED=1 scripts/deploy_engine.sh` |
| Plain functions | Formulas in `engine/metrics/calc/` (no state, no I/O); Azure SDK clients only in `engine/service.py`, injected into `sinks_azure.py` |
| Numbers | Every number comes from code and carries evidence (event IDs, frames); nothing reads `answer-keys/` except `tests/metrics/test_truth.py` |
| Azure changes | Ask before creating any resource; the commands needed are in the README |

**Others build on this:**

| Teammate | Builds on | Where |
|---|---|---|
| Tactical Intelligence | Optional: `PressureSample` per frame and `PassValues` per pass, by direct call (tactics currently computes its own); both share the `stats` hub, kinds don't overlap | README §Tactical Intelligence |
| Insight Generation (Stats API, MCP) | Cosmos `metrics`: cumulative `player:{id}:{clock}` totals, `event:{id}:{version}` results | README §Insight Generation |
| Broadcast, Audience | `stats` hub: `positions`, `player_totals`, `heatmap`, `pass`, `shot`, `xg`; number-only cues with `type=cue` | README §Broadcast and Audience |
| Platform | Before `METRICS_ENABLED=1`: Cosmos container `metrics` and `id-engine`'s Cosmos role on it (the `stats` hub exists); optional `cues` consumer group | README §Platform |
| Data Ingestion | `engine/service.py` fans the router hook out to metrics and tactics (`fan_out`) | README §Data Ingestion |
| Match Simulation | `provider_xg` on every shot; realistic acceleration | README §Match Simulation |

## Lane 1: Match Simulation

`sim/` is the real simulator. It reuses the feed writers, mess rules and streamer from `tests/fixturegen/`, so its feeds follow ingestion §13 and run through the deployed ingestion unchanged.

| Task | Command |
|---|---|
| Generate a match (feeds + answer key + truth files) | `python -m sim generate --storyline red_card --out local_feeds/m001` |
| Storylines | `red_card` (m001), `comeback` (m002), `switch` (m003), `late_drama` (m004), `press_fade` (m005), `storm` (m006); `random --seed N` invents a new match story per seed; or a JSON file |
| Short match for quick tests | add `--minutes 5` |
| Run ingestion on it | `python -m engine.local --feeds local_feeds/m001/feeds --out local_out/m001 --match m001` |
| Stream into Azure | `python -m sim stream --feeds local_feeds/m001/feeds --speed 10` |
| Tests | `python -m pytest tests/sim` (full-match tests take about a minute each) |
| Match control page, local (counts instead of sending) | `python -m sim.control --dry-run --port 8765`, then open http://localhost:8765 |
| Match control, live | https://offball-sim.whitemoss-2f18829c.westus2.azurecontainerapps.io (no passcode) |
| Deploy match control to Azure (Docker + `az login`) | `[CONTROL_PASSCODE=…] scripts/deploy_sim.sh`: Container App `offball-sim` in `offball-env`, identity `id-sim` with send-only access to the raw hubs |

Output folders: `feeds/` (feed_a.jsonl, feed_b.jsonl), `answer-keys/` (answer_key.json with tactic changes and true player stats, frames_truth.npz with possession per frame), `match/` (match.json, prematch.json, events.jsonl, frames.parquet).

## Lane 1: Tactical Intelligence

`engine/tactics/` reads the merge stage's clean output (same router hook as Performance Metrics) and needs nothing else.

| Task | Command |
|---|---|
| Run on a generated match | `python -m engine.tactics.local --feeds local_feeds/m001/feeds --match m001 --answer-key local_feeds/m001/answer-keys/answer_key.json` |
| Output | `local_out/<match>/tactics/`: windows, series, territory, notes, triggers (JSONL) and `scoring.json` |
| Tune thresholds | JSON file passed with `--config` or `TACTICS_CONFIG`; every field of `engine/tactics/config.py` |
| Tests | `python -m pytest tests/tactics` |
| Live | Engine with `TACTICS_ENABLED=1` publishes to hubs `stats` (consumer groups `bridge`, `fabric`) and `triggers` (`agents`, `fabric`); deploy with `TACTICS_ENABLED=1 scripts/deploy_engine.sh` |

## Lane 2: Insight Generation

`insights/` turns each Tactical Intelligence trigger into an insight with 12 captions (analyst,
casual, supporter_home, supporter_away × en, es, hi), per [lld-insight-generation.md](docs/design/lld-insight-generation.md).
Every number in a caption comes from the trigger's facts (`insights/facts.py`) or an MCP tool result.

Agent team (`insights/agents.py`, `insights/workflow.py`, prompts in `insights/prompts/`): coordinator
(code) → tactics agents (home, away, in parallel, MCP tools) → shift explainer → storyteller (one call
per language, in parallel) → checker (`insights/checker.py`: numbers, units, direction words, expect
targets, jargon, word limits) with up to 2 rewrites, then the template per caption. A middleware pins
every tool call's `as_of` to the trigger's moment, enforces tool budgets and records results for the
checker.

| Task | Command |
|---|---|
| Insights for a match, added to its replay | `python -m insights.local --feeds local_feeds/m001/feeds --match m001 --replay web/public/replays/m001.json` (after `scripts/build_replay.py`, which rewrites the file) |
| Output | `local_out/<match>/insights/insights.jsonl`; inputs cached in `local_out/<match>/insights/data/` |
| With the agent team (Foundry) | add `--agents` (needs `az login` with access to `offball-ai-kr2610`); about 3 minutes per match |
| MCP stats server alone | `OFFBALL_MATCH_DATA=local_out/m001/insights/data python -m mcp_stats.server` (stdio; works with any MCP client) |
| Tests | `python -m pytest tests/insights` |

**Azure:** AI Services (Foundry) `offball-ai-kr2610` in **Sweden Central** (the subscription allows
only canadacentral, mexicocentral, swedencentral, westus2 and belgiumcentral; westus2 has no small-model
quota), endpoint `https://offball-ai-kr2610.cognitiveservices.azure.com/`, deployment `gpt-5-mini`
(GlobalStandard, 100K TPM; call it with `reasoning_effort="minimal"`). Key access is off: use Entra ID
(`Cognitive Services OpenAI User`, `Cognitive Services User`). gpt-4o-mini is retired and gpt-4.1-mini
has no quota here.

