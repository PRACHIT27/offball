"""Engine core: routes normalized messages to one merge stage per match, stores the output and
snapshots state. Storage and snapshots are injected, so this runs in tests without Azure."""

import json
from collections.abc import Callable
from typing import Protocol

from pydantic import TypeAdapter

from engine.merge.outputs import MergeOutput
from engine.merge.stage import MergeStage, parse_wall
from ingest.clean import NormalizedMessage

normalized_adapter: TypeAdapter[NormalizedMessage] = TypeAdapter(NormalizedMessage)

# A match with no messages for this long has its wait window released (end of match, breaks)
IDLE_FLUSH_MS = 5_000


class SilverStore(Protocol):
    def write(self, outputs: list[MergeOutput]) -> None: ...
    def flush(self, counts: dict | None = None) -> None: ...


class SnapshotStore(Protocol):
    def load(self, match_id: str) -> str | None: ...
    def save(self, match_id: str, state_json: str) -> None: ...


class EngineCore:
    def __init__(self, store_for: Callable[[str], SilverStore], snapshots: SnapshotStore,
                 router: Callable[[list[MergeOutput]], None] = lambda outputs: None) -> None:
        self.store_for = store_for
        self.snapshots = snapshots
        # Performance Metrics plugs in here (LLD §9); a no-op until it exists
        self.router = router
        self.stages: dict[str, MergeStage] = {}
        self.stores: dict[str, SilverStore] = {}
        self.last_seen: dict[str, float] = {}
        # Normalizer → engine arrival lag per feed (ms), for the delay report; drained by the caller
        self.arrival_lag: dict[str, list[float]] = {"A": [], "B": []}

    def _stage(self, match_id: str) -> MergeStage:
        if match_id not in self.stages:
            saved = self.snapshots.load(match_id)
            self.stages[match_id] = (MergeStage.from_state(json.loads(saved)) if saved
                                     else MergeStage(match_id))
            self.stores[match_id] = self.store_for(match_id)
        return self.stages[match_id]

    def handle(self, body: str | bytes, props: dict, now_ms: float) -> list[MergeOutput]:
        msg = normalized_adapter.validate_json(body)
        match_id = props["match_id"]
        timings = (msg.batch.timings if msg.kind == "frames" else msg.event.timings
                   if msg.kind == "event" else getattr(msg, "timings", {}))
        if timings.get("normalized_at"):
            feed = "B" if msg.kind == "frames" else "A"
            self.arrival_lag[feed].append(now_ms - parse_wall(timings["normalized_at"]))
        stage = self._stage(match_id)
        # Arrival time, not the provider's send time: feed health is judged on what actually
        # reaches the engine, and merged_at records when the merge really happened (FR-25)
        out = stage.handle(msg, now_ms)
        self.last_seen[match_id] = now_ms
        self._emit(match_id, out)
        return out

    def tick(self, now_ms: float) -> list[MergeOutput]:
        """Timer: feed health, and release held events of matches that have gone quiet."""
        out_all: list[MergeOutput] = []
        for match_id, stage in self.stages.items():
            out = stage.tick(now_ms)
            idle = now_ms - self.last_seen.get(match_id, now_ms) > IDLE_FLUSH_MS
            # Never force out events before the clock is aligned; the stage's own give-up
            # (in tick) covers a feed B that never arrives
            if stage.buffer and stage.clock.ready and idle:
                out += stage.flush(now_ms)
            self._emit(match_id, out)
            out_all += out
        return out_all

    def _emit(self, match_id: str, out: list[MergeOutput]) -> None:
        if out:
            self.stores[match_id].write(out)
            self.router(out)

    def checkpoint(self) -> None:
        """Make stored output durable, then snapshot state (always ahead of the hub checkpoint,
        which is safe: replayed messages are dropped as duplicates)."""
        for match_id, stage in self.stages.items():
            counts = dict(stage.counts) | {"clock_offset_ms": stage.offset_ms}
            self.stores[match_id].flush(counts)
            self.snapshots.save(match_id, json.dumps(stage.to_state()))
