# Performance Metrics: hand-off notes

Numbers about players, the ball and single actions, built to
[lld-performance-metrics.md](../../docs/design/lld-performance-metrics.md). It runs inside the match
engine. The merge stage hands it every clean message by direct call, and it sends results to the
`stats` hub, Cosmos `metrics`, and Tactical Intelligence.

**If you build on this, read your section in [Who builds on what](#who-builds-on-what).**

## Run it

```sh
uv venv --python 3.12 .venv && uv pip install --python .venv -e '.[dev,azure]' azure-functions
python -m tests.fixturegen --out local_feeds/fx01 --mess light
python -m engine.metrics.local --feeds local_feeds/fx01/feeds --out local_out --match fx01
pytest tests/metrics
```

Local mode writes `local_out/metrics/fx01/stats.jsonl`, `cues.jsonl` and `metrics.json`. These are
the same messages and documents the Azure path sends. A 90-minute fixture match takes about 40 s
and peaks at about 155 MB.

On Azure, `python -m engine.service` (Kanika's match engine Container App) runs the merge stage and
Performance Metrics together. Before metrics can run there, the resources listed under
[Platform](#platform-and-whoever-runs-az) must exist. Until then, set `METRICS_ENABLED=0`.

## What is built

| PM | What | Where |
|---|---|---|
| 1, 2, 6 | Name-tag values, smoothed speed, ball speed | `frame_processor.py` → `positions` |
| 3, 4, 5 | Distance, sprints, top speed; alerts (≥ 32 km/h, new match top after 10:00, 10 km) | `frame_processor.py`, `totals.py` |
| 7–11 | Shot and pass speed, pass distance, accuracy, difficulty | `event_processor.py`, `calc/pass_model.py` |
| 12 | Completion vs expected | `totals.py` (`player_totals`) |
| 13–15 | Provider xG, 10th–90th percentile range, chance story, big chances | `calc/xg_range.py` |
| 16–18 | Open options, decision score + best option, decoy run credit | `calc/pass_model.py`, `calc/decoy.py` |
| 21–24 | `stats` messages, number-only cues on air, evidence on everything, Cosmos snapshots | `publisher.py`, `sinks_azure.py` |
| 25 | Corrections and deletions recompute, fix totals, update or withdraw cues | `correction_handler.py` |
| 26 | Pressure and pass values to Tactical Intelligence | `models.py` (`PressureSample`, `PassValues`) |
| 27 | Truth comparison: distance ±3%, top speed ±0.3 m/s, sprints ±2 | `tests/metrics/test_truth.py` |
| 28 | Local mode | `local.py` |
| 29 | Heatmaps 21 × 14, whole match and last 15 min, every 10 s | `totals.py`, `frame_processor.py` |
| 19, 20 | Pressure seconds, fatigue | **Not built** (Should / Nice) |

## Who builds on what

### Tactical Intelligence

**Pressure and pass values arrive by direct call, in the same process.** Register a callback on
the publisher:

```python
Publisher(sinks, to_tactics=[tactics.on_metrics])   # receives PressureSample | PassValues
```

- **`PressureSample`**, every frame (25 Hz) when someone has the ball: `carrier_id`, `team_id`,
  `pressure` (0–1), `presser_id`, `frame`, `match_clock_ms`, `period`.
  - The carrier is the player nearest the ball, within 1.5 m, with the ball below 1.5 m.
  - Your design counts a press at `pressure ≥ 0.75`.
- **`PassValues`**, every pass: `passer_id`, `receiver_id`, `completed`, `p_complete`,
  `value_start`, `value_end`, `value_gain` (pitch value, LLD §5.3).
  - A correction sends it again with a higher `version`; a deletion sends `status: "deleted"`.
  - Keep the highest version.
- **Importable functions:** `engine.metrics.calc.pressure.pressure` and
  `engine.metrics.calc.pitch_value.pitch_value` / `attack_x`, so both domains use the same formulas.
- **Reusable state:**
  - `engine.metrics.memory.FrameMemory` (last 10 s, smoothed, NumPy rings) and `Roster` can be
    shared, so frames aren't buffered twice.
  - To plug in next to metrics, wrap `MetricsRouter` or add your own router to
    `EngineCore(router=…)` in `engine/service.py`.
- **Please confirm or change these shapes before you build on them.** They are our proposal,
  not a published contract.

### Insight Generation (Stats API and MCP server, `mcp_stats/`)

Cosmos container `metrics`, partition `/match_id`. Every document has `id`, `match_id`, `type`,
`doc_type`, `period`, `match_clock_ms` and `body`.

| `id` | When | `body` |
|---|---|---|
| `player:{player_id}:{clock}` | Every 10 s of match time | `distance_m`, `sprints`, `top_speed_ms`, `passes`, `passes_completed`, `pass_accuracy`, `completion_vs_expected`, `shots`, `xg`, `sum_x`, `sum_y`, `frames_on`, `avg_position` |
| `event:{event_id}:{version}` | Every pass and shot, and every new version | `type`, `status`, `player_id`, `team_id`, plus the pass or shot values below |

- **Totals are cumulative from kick-off.** `get_player_stats(player, from, to)` is the document at
  `to` minus the one at `from`. The average position over the range is
  `Δsum_x / Δframes_on`, `Δsum_y / Δframes_on`.
- **`as_of`:** filter on `match_clock_ms` (and `period`). In period 2 the clock starts at
  2,700,000.
- **Events:** keep the highest `version` per `event_id`, and drop `status: "deleted"`.
- **Every number has evidence:** `event_ids` and frame numbers are in the `stats` messages, and
  each event document is keyed by its event.

### Broadcast (cue manager, PubSub bridge) and Audience (viewer screen)

Everything goes on the **`stats` hub**, partition key `match_id`, as one JSON body per message.
Use the message properties to route it:

| Property | Values |
|---|---|
| `type` | `stats` (screen data) or `cue` (number-only overlay cue) |
| `kind` | stats kind or cue kind (below) |
| `match_id`, `emitted_at` | Match, UTC send time for delay measurement |

**Stats kinds:**

| Kind | Rate | `values` |
|---|---|---|
| `positions` | Every 200 ms | `frames`: the raw 25 Hz frames of the batch (`ball` [x,y,z], `players` {id: [x,y]}); `tags`: {id: `speed_ms`, `speed_kmh`, `distance_m`, `pressure`} for name tags and pressure rings; `ball_speed_ms` |
| `player_totals` | Every 10 s | `players`: {id: totals as in the Cosmos doc} |
| `heatmap` | Every 10 s, one per team | `grid` [21, 14]; `players` {id: {`match`, `last_15`}}, shares that sum to 1 (5 m cells) |
| `pass` | Per pass (and new versions) | `receiver_id`, `completed`, `distance_m`, `speed_ms`, `difficulty`, `p_complete`, `lane_opponents`, `pressure_passer`, `pressure_receiver`, `open_options`, `decision_score`, `decoy_credit`, `value_gain`; `best_option` {player_id, x, y} for the ghost arrow |
| `shot` | Per shot | `outcome`, `speed_ms`, `speed_kmh`, `xg`, `big_chance` |
| `xg` | After any shot change, per team | `shots`, `total_xg`, `range` [lo, hi], `big_chances`, `big_chance_share`, `text` ("1–3 goals expected, mostly from 2 big chances") |

A stats message carries `version` and `status`. A corrected pass is sent again with a higher
`version`; a deleted one with `status: "deleted"`.

**Cue kinds** (HLD cue v0.2, plus `period`):
- They are created with `status: "on_air"` and `caption_source: "none"`.
- When their data changes they get a new `version`.
- They become `status: "withdrawn"` with `reason: "correction"` when their evidence goes.

| Kind | Slot (Broadcast LLD §6) | `data` |
|---|---|---|
| `speed_alert` | Pitch overlay, priority 4 | `player_id`, `type` (`fast` / `match_top_speed`), `speed_ms`, `speed_kmh` |
| `distance_milestone` | Pitch overlay, priority 4 | `player_id`, `distance_m` |
| `pass_arc` | Pitch overlay, priority 4 | `passer_id`, `receiver_id`, `start`, `end`, `completed`, `distance_m`, `speed_ms`, `difficulty` |
| `shot_speed` | Pitch overlay, priority 4 | `player_id`, `speed_ms`, `speed_kmh`, `xg`, `outcome` |
| `best_option` | Pitch overlay, priority 3 | `passer_id`, `chosen_id`, `best` {player_id, x, y, value, open}, `decision_score` |
| `decoy_run` | Pitch overlay, priority 3 | `runner_id`, `credit`, `pulled`, `path` [start, end], `defenders` {id: [start, end]}, `receiver_id` |
| `xg_summary` | Side panel | `team_id` + the `xg` values above; one cue per team, updated in place |

### Platform (and whoever runs `az`)

Kanika's `azure-setup.sh` already creates `id-engine` and its roles for the merge stage. Its Cosmos
role is scoped to `events` only. Metrics needs two more resources and two more roles in
`offball-rg`, and the commands are below. **They have not been run**: ask the owner first, as the
Lane 1 rules require. They could also go into `azure-setup.sh` step 10.

```sh
RG=offball-rg; EH=offball-eh-kr2610; COSMOS=offball-cosmos-kr2610
ENGINE_PRINCIPAL_ID=$(az identity show -g $RG -n id-engine --query principalId -o tsv)

# stats hub: the engine sends; the PubSub bridge, cue manager and Fabric each read with their own group
az eventhubs eventhub create -g $RG --namespace-name $EH --name stats \
  --partition-count 4 --retention-time 24 --cleanup-policy Delete
for g in bridge cues fabric; do
  az eventhubs eventhub consumer-group create -g $RG --namespace-name $EH --eventhub-name stats --name $g
done
az role assignment create --assignee-object-id $ENGINE_PRINCIPAL_ID --assignee-principal-type ServicePrincipal \
  --role "Azure Event Hubs Data Sender" \
  --scope $(az eventhubs eventhub show -g $RG --namespace-name $EH --name stats --query id -o tsv)

# Cosmos metrics container; the engine writes it, the Stats API reads it
az cosmosdb sql container create -g $RG --account-name $COSMOS --database-name offball \
  --name metrics --partition-key-path /match_id
az cosmosdb sql role assignment create -g $RG --account-name $COSMOS \
  --role-definition-id 00000000-0000-0000-0000-000000000002 \
  --principal-id $ENGINE_PRINCIPAL_ID --scope "/dbs/offball/colls/metrics"
```

- **Engine Container App environment variables:** `AZURE_CLIENT_ID`, `EVENTHUB_NAMESPACE`,
  `COSMOS_ENDPOINT` and `STORAGE_ACCOUNT_URL` (as before), plus optional `METRICS_ENABLED`
  (default `1`).
- **Snapshots:** metrics state is saved in Blob `checkpoints/metrics/{match_id}.json`, apart
  from the merge stage's `checkpoints/engine/`.
- **Volume:** about 5 messages/s per match on `stats` (`positions` about 5 KB each, heatmaps
  about 35 KB every 10 s). One throughput unit is plenty.

### Data Ingestion (Kanika)

- **Contract:** metrics consumes the proposed `contracts/ingestion` v1.0.0 as is. Performance
  Metrics agrees to it.
- **`engine/service.py`** (your async version) now builds `MetricsRouter` and passes it as
  `EngineCore(router=…)`.
  - Metrics runs inside `core.handle`, in your worker thread, so its sends block like your Cosmos
    and Blob calls.
  - Both checkpoint calls go through `checkpoint()`, which runs `core.checkpoint()` and then
    `metrics.checkpoint()`.
- **Deploying:** your deployed engine runs `main`, which has no metrics. If you deploy
  `performance-metrics` before the `stats` hub and Cosmos `metrics` exist, add
  `{"name": "METRICS_ENABLED", "value": "0"}` to the env list in `scripts/deploy_engine.sh`.
  Otherwise every send fails and fills the logs.
- **No change to `engine/core.py`.** `BlobSnapshots` in `engine/store_azure.py` gained a `prefix`
  argument (default `engine`, so merge-stage snapshots don't move). Metrics uses `metrics`, so the
  two can never overwrite each other.
- Metrics reads only the merge outputs (`EventUpsert`, `EventDelete`, `FramesOut`, `Prematch`). It
  assumes:
  - events arrive after their frames (about 1.5 s later in the fixtures);
  - frame numbers count from each period's start;
  - the prematch names the home club.
- A `period_end` event releases any pass or shot still waiting for frames.

### Match Simulation

- **Every shot needs `provider_xg` in feed A.** Metrics doesn't model xG (PM-13).
- **The stand-in fixture (`tests/fixturegen`) teleports players** (`give()`) and changes speed
  instantly. Metrics treats any movement faster than 12 m/s as a jump in position, not running.
  The truth test skips moments with acceleration a person can't produce. The real simulator caps
  acceleration (LLD §4.3), so both guards should stop mattering.
- `answer-keys/` is read only by `tests/metrics/test_truth.py`, never by the live path.

## Decisions and open items

- **Speeds above 12 m/s** are tracking jumps. Smoothing and speed restart at a jump, and no
  distance is counted across it.
- **The best-option ghost arrow** only shows when `decision_score < 0.4` and the best option was
  open. At 0.7 it fired on more than half of all passes.
- **Positions travel on `stats`** (`positions`, 5/s with all 25 Hz frames). The fast path and the
  name tags need them on screen.
- **The 10 s frame memory isn't snapshotted.** After a restart it refills from new frames, so an
  event waiting for frames at that moment uses fewer frames (`tests/metrics/test_azure_path.py`).
- **Message shapes are not yet in `contracts/`.** They live in `models.py` until the team agrees to
  publish them.
