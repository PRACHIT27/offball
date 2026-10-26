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
