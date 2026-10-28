# OffBall: submission

Inside the Game: Developer Hackathon (Microsoft × Premier League). Everything here is synthetic:
fictional clubs (Riverside Athletic, Northgate United, Kestrel Vale), fictional players, simulated
matches.

## Try it (no login needed)

| What | Link |
|---|---|
| **Viewer screen** (three recorded matches) | https://jolly-cliff-0ccede51e.4.azurestaticapps.net |
| The 70' red card, analyst view | https://jolly-cliff-0ccede51e.4.azurestaticapps.net/?match=m001&t=4300&type=analyst&lang=en |
| Before/after board for that red card (76') | https://jolly-cliff-0ccede51e.4.azurestaticapps.net/?match=m001&t=4560&type=analyst&lang=en |
| The same moment four ways | https://jolly-cliff-0ccede51e.4.azurestaticapps.net/?match=m001&t=4302&view=four&club=home&lang=en |
| **Match control:** stream a new simulated match through the live Azure pipeline | https://offball-sim.whitemoss-2f18829c.westus2.azurecontainerapps.io |
| Live agent captions for that match (while the insights service is running) | https://offball-insights.whitemoss-2f18829c.westus2.azurecontainerapps.io |

**On the viewer:**
- **Controls:** pick a match (red card, comeback, switch), press ▶, change speed (1× / 5× / 10×),
  or press **Next moment**. Space plays and pauses; ← → move 10 s.
- **Viewer types:** **Casual**, **Analyst**, **Supporter** (pick a club), **Player** (tap any
  player), or **Four ways** to see all four at once. EN / ES / HI switch the captions' language.
- **Analyst panel:**
  - before/after board after a goal or red card;
  - xG race and shot map;
  - passing quality, line height, control vs chaos, pressing and the passing network;
  - leaders;
  - tap a player for their card and heatmap.

## The pitch

**OffBall sees where every player is, reads the tactics, notices when they change, and explains it
on screen. Visuals first, a short caption alongside.**

Broadcasts explain *events*: a goal, a card, a pass. The interesting part of football is the shape
of the teams between events: a line dropping ten metres after a red card, a press switching on, a
switch to a back three. OffBall measures that from player positions, detects when it changes,
predicts what will happen next, then checks against the numbers whether it did.

**How it works, one pipeline in five stages:**
1. **Ingest:** a simulator plays a full match at 25 frames a second and streams it as two
   deliberately messy provider feeds (different units, clocks, IDs, duplicates, late corrections).
   Data Ingestion cleans, merges and time-aligns them.
2. **Interpret:**
   - Performance Metrics computes every number from positions: speeds, sprints, pass difficulty,
     open options, decision quality, decoy runs, pressure, xG range.
   - Tactical Intelligence tracks each team's line height, pressing, shape, style and control,
     and raises triggers when they change.
3. **Explain:** a team of agents on Microsoft Agent Framework explains each trigger. They predict
   first ("expect Northgate to drop deeper"), then confirm or retract four minutes later.
   - They get numbers only through our MCP stats server.
   - A checker blocks any number the tools didn't return.
   - Spanish and Hindi captions are translated back and checked again, and every caption is
     screened for safety.
4. **Render:** the viewer draws it on the pitch: pass arcs coloured by difficulty, the better
   option, pressure rings, both defensive lines, a before/after board.
5. **Personalize:** captions for casual fans, analysts, each club's supporters and a followed
   player, in three languages.

**Code computes every number; agents only explain.** Every caption traces back to event and window
IDs.

## Results (from the code, `scripts/results.py` and Insight Generation's runs)

| Measure | Result |
|---|---|
| Events recovered from the two messy feeds | **100.0%** average over 6 storylines (99.9–100%), clocks aligned within 0–40 ms, 0 dead letters |
| Engine speed (metrics + tactics per 200 ms batch) | **1.4–1.8 ms** p95 (target ≤ 20 ms) |
| Captions written by the agent team after checking | **941 of 1,320 (71%)**; the rest are template fallbacks |
| Unchecked numbers on air | **0**: every caption passed the checks or is a template |
| Agent latency | expect insights median 8 s; others median 20 s |
| Scripted tactic changes detected (vs the hidden answer key) | **17 of 38 (45%)**, 88 false alarms |
| Player stats vs simulator truth (realistic feed noise) | top speed within 0.3 m/s for 74–96% of players; distance median error 5–7% |

Full tables: [results/RESULTS.md](../results/RESULTS.md) and
[docs/insight-generation.md](insight-generation.md#results).

## Microsoft technology used

| Technology | Where |
|---|---|
| Microsoft Agent Framework | The agent team: tactics agents, shift explainer, storyteller; MCP tools; middleware (`insights/`) |
| Microsoft Foundry (Azure AI Services) | `gpt-5-mini` deployment, keyless via Entra ID |
| Model Context Protocol | Our stats server (`mcp_stats/`), the only way agents read numbers, with an `as_of` cut-off |
| Azure AI Translator | Back-translating Spanish and Hindi captions for checking |
| Azure AI Content Safety | Screening every caption |
| Azure Event Hubs | `raw-events`, `raw-tracking`, `normalized`, `stats`, `triggers`, with Capture on the raw hubs |
| Azure Functions | The two feed normalizers (Flex Consumption) |
| Azure Container Apps | The match engine (ingestion merge, metrics, tactics), the insights service, match control |
| Azure Cosmos DB | Clean events (all versions), metrics snapshots |
| Azure Blob Storage | Raw feed archive (Bronze), clean frames as Parquet, checkpoints |
| Azure Static Web Apps | The viewer screen |
| Application Insights | Engine logs and delay measurements |
| Managed identities | One per service, least-privilege roles; no keys in code |
| GitHub Actions | Lint, tests and web build on every PR; screen deploy on `main` |

## How we used GitHub Copilot and the Azure MCP Server

> **TODO (team):** describe your actual use of GitHub Copilot (Agent Mode, coding agent, code review)
> and the Azure MCP Server here. The rules ask for this; only write what you really did.

## Honesty notes

- **Synthetic only:** no real Premier League data, clubs, players or footage.
- **Positions, not video:** everything is computed from simulated tracking positions and events.
  There is no computer vision.
- **The viewer plays recorded matches:** each one is a simulated match run through the real
  pipeline code, with the agents' captions. A live match from match control runs through the
  deployed Azure pipeline, and its captions appear on the live captions page. The viewer itself
  is not yet connected to the live stream.
- **Not built:**
  - the Broadcast cue manager and producer console;
  - Web PubSub live push;
  - the Fabric dashboard;
  - half-time and full-time recaps;
  - spoken captions;
  - azd/Bicep (we deploy with scripts).
