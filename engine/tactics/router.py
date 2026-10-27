import json
import logging
import time
from collections.abc import Callable

from engine.merge.outputs import FramesOut, MergeOutput, Prematch
from engine.tactics.config import TacticsConfig
from engine.tactics.engine import TacticsEngine

log = logging.getLogger("offball.tactics")
Publish = Callable[[list[dict]], None]
PrematchLoader = Callable[[str], dict | None]


def match_of(msg: MergeOutput) -> str | None:
    if isinstance(msg, FramesOut):
        return msg.batch.match_id
    event = getattr(msg, "event", None)
    return event.match_id if event is not None else getattr(msg, "match_id", None)


class TacticsRouter:
    def __init__(self, publish: Publish, prematch_loader: PrematchLoader | None = None,
                 cfg: TacticsConfig | None = None):
        self.publish = publish
        self.prematch_loader = prematch_loader
        self.cfg = cfg or TacticsConfig.load()
        self.engines: dict[str, TacticsEngine] = {}
        self.counts = {"stats": 0, "triggers": 0}
        self.tried: dict[str, float] = {}

    def engine(self, match_id: str) -> TacticsEngine:
        eng = self.engines.get(match_id)
        if eng is None:
            eng = self.engines[match_id] = TacticsEngine(match_id, self.cfg)
        return eng

    def _ensure_ready(self, eng: TacticsEngine) -> None:
        if eng.ready or self.prematch_loader is None:
            return
        now = time.monotonic()
        if now - self.tried.get(eng.match_id, -1e9) < 10:
            return
        self.tried[eng.match_id] = now
        prematch = self.prematch_loader(eng.match_id)
        if prematch:
            eng.dispatch(Prematch(match_id=eng.match_id, prematch=prematch))

    def __call__(self, outputs: list[MergeOutput]) -> None:
        results: list[dict] = []
        for msg in outputs:
            match_id = match_of(msg)
            if match_id is None:
                continue
            eng = self.engine(match_id)
            if isinstance(msg, FramesOut):
                self._ensure_ready(eng)
            try:
                results += eng.dispatch(msg)
            except Exception:
                log.exception("tactics failed on %s for match %s", msg.kind, match_id)
        if results:
            for r in results:
                self.counts[r["sink"]] += 1
            self.publish(results)


class EventHubPublisher:
    def __init__(self, namespace: str, credential, hubs: dict[str, str] | None = None):
        from azure.eventhub import EventHubProducerClient

        self.hubs = hubs or {"stats": "stats", "triggers": "triggers"}
        self.producers = {sink: EventHubProducerClient(fully_qualified_namespace=namespace,
                                                       eventhub_name=hub, credential=credential)
                          for sink, hub in self.hubs.items()}

    def __call__(self, results: list[dict]) -> None:
        from azure.eventhub import EventData

        by_key: dict[tuple[str, str], list[dict]] = {}
        for r in results:
            by_key.setdefault((r["sink"], r["match_id"]), []).append(r)
        for (sink, match_id), items in by_key.items():
            producer = self.producers[sink]
            batch = producer.create_batch(partition_key=match_id)
            for r in items:
                event = EventData(json.dumps(r, separators=(",", ":")))
                event.properties = {"match_id": match_id, "kind": r.get("kind") or r.get("type")}
                try:
                    batch.add(event)
                except ValueError:
                    producer.send_batch(batch)
                    batch = producer.create_batch(partition_key=match_id)
                    batch.add(event)
            producer.send_batch(batch)

    def close(self) -> None:
        for p in self.producers.values():
            p.close()
