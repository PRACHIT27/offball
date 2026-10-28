# Contracts

Shared schemas between lanes (HLD §6). Changing anything here needs all three to agree and a
VERSION.md entry in the same commit.

| Folder | Producer | Status |
|---|---|---|
| [`ingestion/`](ingestion/) | Data Ingestion (Lane 1) | **Proposed v1.0.0**, waiting for Lanes 2 and 3 to agree |
| [`broadcast/`](broadcast/) | Performance Metrics → Broadcast, Audience | **v0.2**: documents the cue and `stats` message the engine already sends |
| trigger, MCP tools | Tactical Intelligence, Insight Generation | Not yet published |

## Ingestion: clean event and frame (v1.0.0)

Everything after Data Ingestion sees only these. The files are JSON Schema (draft 2020-12),
generated from the Pydantic models in `ingest/clean.py`, `ingest/raw.py` and
`engine/merge/outputs.py`. Don't edit them by hand: change the model, then run
`python -m engine.contracts`. A test fails if a file and its model disagree.

| File | What it is | Consumers |
|---|---|---|
| [`clean-event.schema.json`](ingestion/clean-event.schema.json) | One match event, cleaned and aligned to the match clock | Metrics, Tactical Intelligence |
| [`clean-frame-batch.schema.json`](ingestion/clean-frame-batch.schema.json) | Tracking frames at 25 Hz, in batches | Metrics, Tactical Intelligence |
| [`prematch.schema.json`](ingestion/prematch.schema.json) | Team sheets; extra fields (club and manager profiles, history) pass through unchanged | Tactical Intelligence, Insight Generation, Audience |
| [`merge-output.schema.json`](ingestion/merge-output.schema.json) | Everything the merge stage hands on, told apart by `kind` | The router in the match engine |

### Rules consumers can rely on

- **Clock:** `match_clock_ms` + `period`. Period 2 starts at 2,700,000 ms. Wall-clock time only
  appears in `emitted_at` and `timings`.
- **Pitch:** metres, 105 × 68, origin at a corner, home attacks toward x = 105 in both halves.
- **IDs:** clubs `RIV`, players `RIV-07`, events `e-004512`.
- **Corrections:** same `event_id`, higher `version`; keep the highest. A deletion arrives as
  `event.delete` with `status: "deleted"`. If the event was already released, a
  `notice.correction_applied` follows.
- **Order:** events are released in match-clock order after a 1.5 s wait window. One that arrives
  later than that comes as `event.upsert` with `late: true`.
- **Frames:** `frame` counts from 0 at each period's start. Gaps of up to 12 frames (0.5 s) are filled
  and marked `interpolated: true`; longer gaps are left open and announced with notices.

### Event types

`pass`, `take_on`, `foul`, `tackle`, `interception`, `clearance`, `shot`, `card`, `sub_off`,
`sub_on`, `period_start`, `period_end`, `conditions`, `stoppage_start`, `stoppage_end`.

`details` is set only on these types:

| Type | `details` |
|---|---|
| `conditions` | `{"weather": "heavy_rain", "temperature_c": 13, "pitch": "wet"}` |
| `stoppage_start`, `stoppage_end` | `{"stoppage_id": "s1", "reason": "injury"}` |

### Merge outputs (`kind`)

| `kind` | Payload | `details` |
|---|---|---|
| `event.upsert` | `event` (clean event), `late` | – |
| `event.delete` | `event` (clean event, `status: "deleted"`) | – |
| `frames` | `batch` (clean frame batch) | – |
| `prematch` | `prematch` | – |
| `notice.gap_start`, `notice.gap_end` | notice | `missing_frames`, `first_frame` |
| `notice.feed_stopped` | notice | `feed` (`A` or `B`), `last_seen_ms` (wall clock) |
| `notice.feed_resumed` | notice | `feed`, `silent_ms` |
| `notice.correction_applied` | notice | `event_id`, `version`, `action` (`upsert` or `delete`) |
| `conditions.changed` | notice | as the `conditions` event |
| `stoppage.start`, `stoppage.end` | notice | as the stoppage events |

`notice_id` is deterministic, so a replayed notice overwrites the earlier one instead of
doubling. The feed-health notices (`feed_stopped`, `feed_resumed`) have no `period` or
`match_clock_ms` until the match clock has started.

### How the outputs reach you

Metrics and Tactical Intelligence run inside the match engine and get merge outputs in-process
from the router. Other domains don't read ingestion's storage (CLAUDE.md rule 6); they ask the
owning domain.

## Broadcast: overlay cue and stats message (v0.2)

Generated the same way, from `engine/metrics/models.py` (`Cue`, `StatsMessage`), with
`python -m engine.contracts`. They describe what the engine already sends on the `stats` hub
(cues carry message property `type=cue`). External graphics systems can read the same cues from
the cue manager: `GET /api/matches/{id}/cues` or the Web PubSub group `match-{id}`.

| File | What it is | Consumers |
|---|---|---|
| [`cue.schema.json`](broadcast/cue.schema.json) | A number-only overlay cue with its `version`, `status` (`on_air` / `withdrawn`), `reason` and `evidence` | Cue manager, viewer screen, Fabric |
| [`stats-message.schema.json`](broadcast/stats-message.schema.json) | One `stats` hub message (`positions`, `pass`, `shot`, `xg`, `player_totals`, `heatmap`) | Cue manager, Insight Generation, Fabric |
