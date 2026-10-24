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
