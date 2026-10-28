# OffBall: submission

Inside the Game: Developer Hackathon (Microsoft × Premier League). Everything here is synthetic:
fictional clubs (Riverside Athletic, Northgate United, Kestrel Vale), fictional players, simulated
matches.

**Demo video (under 2 minutes):** https://youtu.be/xfnb7fFuq_Q

## Try it (no login needed)

| What | Link |
|---|---|
| **Viewer screen** (three recorded matches) | https://jolly-cliff-0ccede51e.4.azurestaticapps.net |
| The 70' red card, analyst view | https://jolly-cliff-0ccede51e.4.azurestaticapps.net/?match=m001&t=4300&type=analyst&lang=en |
| Before/after board for that red card (74') | https://jolly-cliff-0ccede51e.4.azurestaticapps.net/?match=m001&t=4560&type=analyst&lang=en |
| The same moment four ways | https://jolly-cliff-0ccede51e.4.azurestaticapps.net/?match=m001&t=4302&view=four&club=home&lang=en |
| **Match control:** stream a new simulated match through the live Azure pipeline (the first Play wakes the pipeline: about a minute) | https://offball-sim.whitemoss-2f18829c.westus2.azurecontainerapps.io |
| Live agent captions for that match (while the insights service is running) | https://offball-insights.whitemoss-2f18829c.westus2.azurecontainerapps.io |
| **Producer console:** every cue on air for a live match, with **Pull** | https://offball-cues.whitemoss-2f18829c.westus2.azurecontainerapps.io/producer |
| **Fabric Real-Time Dashboard** (needs a sign-in to our Fabric tenant; screenshot below) | [docs/img/fabric-dashboard.png](img/fabric-dashboard.png) |

**Live:** start a match from match control. Within a few seconds it shows up in the viewer's match
picker as **LIVE**. The screen then follows it over Azure Web PubSub: players, pass arcs, cues and
agent captions arrive as the engine computes them. A cue the producer pulls disappears from every
screen at once. Pulling needs the producer passcode, which we give the judges in the submission
form.

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
- **Timeline:** goals, cards, subs and tactic changes, plus a small purple dot for every agent
  insight (hover to read it, click to jump there).
- **Share:** the address bar always holds the match, moment and view; **Copy link** copies it.
- **Live:** when a match is streaming, a red **LIVE** button appears; otherwise **Start a live
  match ↗** opens match control.

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

**Around it:**
- **The cue manager** keeps every cue's versions, corrections and withdrawals, attaches the
  agents' checked captions, and pushes each change to the screens over Web PubSub.
- **A producer console** can pull any cue off air.
- **A Fabric Real-Time Dashboard** shows each match as the engine sees it: line height, pressing,
  control, xG, triggers, what ingestion cleaned up, and how long each engine step took.

**Code computes every number; agents only explain.** Every caption traces back to event and window
IDs.

## Results (from the code, `scripts/results.py` and Insight Generation's runs)

| Measure | Result |
|---|---|
| Events recovered from the two messy feeds | **100.0%** on all 6 storylines, clocks aligned within 0–40 ms |
| Engine speed (metrics + tactics per 200 ms batch) | **4.3–14.1 ms** p95 (target ≤ 20 ms) |
| Insights written by the agent team after checking | **91 of 122 (75%)** in the three recorded matches, 12 captions each; the rest are template fallbacks |
| Unchecked numbers on air | **0**: every caption passed the checks or is a template |
| Agent latency | expect insights median 8 s; others median 20 s |
| Scripted tactic changes detected (vs the hidden answer key) | **14 of 37 (38%)**, 99 false alarms |
| Player stats vs simulator truth (realistic feed noise) | top speed within 0.3 m/s for 78–96% of players; distance median error 3.9–4.3% |

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
| Azure Container Apps | The match engine (ingestion merge, metrics, tactics), the insights service, the cue manager and producer console, match control |
| Azure Cosmos DB | Clean events (all versions), metrics snapshots |
| Azure Blob Storage | Raw feed archive (Bronze), clean frames as Parquet, checkpoints |
| Azure Static Web Apps | The viewer screen |
| Azure Web PubSub | Live push from the cue manager to every screen, one group per match, receive-only client URLs |
| Microsoft Fabric (Real-Time Intelligence) | Eventhouse KQL database `offball` and the Real-Time Dashboard (`scripts/fabric_dashboard.py`); the cue manager streams live matches in |
| Application Insights | Engine logs and delay measurements |
| Managed identities | One per service, least-privilege roles; no keys in code |
| GitHub Actions | Lint, tests and web build on every PR; screen deploy on `main` |

## How we used GitHub Copilot and the Azure MCP Server

- **Our own MCP server.** `mcp_stats/` (`offball-stats`) is the agents' only source of numbers.
  Every tool takes an `as_of` time and never returns anything after it. It is a standard MCP
  server, so any MCP client can use it. `.vscode/mcp.json` registers it for GitHub Copilot Agent
  Mode in VS Code, so you can ask about a match in chat ("who covered the most ground before
  60'?") and get the same checked numbers the agents get. First build the match data with
  `python -m insights.local --feeds local_feeds/m001/feeds --match m001`.
- **How we built it.** Three of us worked in parallel, each with an AI coding agent (Claude Code),
  from the design docs in `docs/design/`. The sessions couldn't see each other, so they stayed
  consistent through `CLAUDE.md` and the change log in `VERSION.md`.

> **TODO (team):** add any GitHub Copilot use (Agent Mode, coding agent, PR review) and any Azure
> MCP Server use here. Only write what you really did.

## Honesty notes

- **Synthetic only:** no real Premier League data, clubs, players or footage.
- **Positions, not video:** everything is computed from simulated tracking positions and events.
  There is no computer vision.
- **Recorded and live:** the three recorded matches are simulated matches run through the real
  pipeline code, with the agents' captions. A live match from match control runs through the
  deployed Azure pipeline and reaches the viewer over Web PubSub.
- **Fabric:** the dashboard's three matches were loaded with `scripts/fabric_load.py`, which runs
  the same engine code over the match feeds. A live match streams in through the cue manager.
  Fabric needs a sign-in, so judges get a screenshot.
- **Not built:**
  - half-time and full-time recaps;
  - spoken captions;
  - azd/Bicep (we deploy with scripts).
