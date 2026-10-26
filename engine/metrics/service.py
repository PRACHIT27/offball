"""Performance Metrics inside the match engine service (LLD §4, ingestion LLD §9).

`MetricsRouter` is the callable passed as `EngineCore(router=…)`: the merge stage's outputs for
every match go through one `MetricsEngine` per match, and the results through the publisher.
`checkpoint()` saves each engine's state next to the merge stage's snapshot, so a restarted
engine resumes its totals, cues and corrections ledger.

Built on by: Data Ingestion's engine/service.py (wires it in), Tactical Intelligence (adds its
callbacks to the publisher's `to_tactics`, or its own router next to this one).
"""

import json

from engine.core import SnapshotStore
from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, MergeOutput
from engine.metrics.publisher import Publisher
from engine.metrics.router import MetricsEngine


def match_of(msg: MergeOutput) -> str:
    match msg:
        case FramesOut():
            return msg.batch.match_id
        case EventUpsert() | EventDelete():
            return msg.event.match_id
    return msg.match_id


def snapshot_key(match_id: str) -> str:
    """Stored next to the merge stage's snapshot (`engine/{match_id}.json` in Blob)."""
    return f"{match_id}.metrics"


class MetricsRouter:
    def __init__(self, publisher: Publisher, snapshots: SnapshotStore | None = None) -> None:
        self.publisher = publisher
        self.snapshots = snapshots
        self.engines: dict[str, MetricsEngine] = {}

    def engine(self, match_id: str) -> MetricsEngine:
        if match_id not in self.engines:
            saved = self.snapshots.load(snapshot_key(match_id)) if self.snapshots else None
            self.engines[match_id] = (MetricsEngine.from_state(json.loads(saved)) if saved
                                      else MetricsEngine(match_id))
        return self.engines[match_id]

    def __call__(self, outputs: list[MergeOutput]) -> None:
        for msg in outputs:
            self.publisher.emit(self.engine(match_of(msg)).dispatch(msg))

    def checkpoint(self) -> None:
        self.publisher.flush()
        if self.snapshots is None:
            return
        for match_id, e in self.engines.items():
            self.snapshots.save(snapshot_key(match_id), json.dumps(e.to_state()))
