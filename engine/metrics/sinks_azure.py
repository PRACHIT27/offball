"""Azure sinks for Performance Metrics. SDK clients are injected (engine/service.py builds them
with the engine's managed identity), so tests run with in-memory fakes and no keys.

- `stats` hub: stats messages and number-only cues, partition key `match_id`. Properties tell
  consumers apart: `type` = `stats` | `cue`, plus `kind`, `match_id`, `emitted_at`.
  Built on by: the PubSub bridge (Broadcast), the cue manager, Fabric Eventstream.
- Cosmos `metrics` (partition `/match_id`): player totals every 10 s and per-event results.
  Built on by: the Stats API behind the MCP server (Insight Generation).
"""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from engine.metrics.models import Cue, MetricDoc, StatsMessage
from engine.metrics.publisher import Shared


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class StatsHubSink:
    def __init__(self, producer, event_data: Callable | None = None,
                 now: Callable[[], str] = utc_now) -> None:
        if event_data is None:
            from azure.eventhub import EventData as event_data
        self.producer = producer
        self.event_data = event_data
        self.now = now

    def write(self, results: list[Shared]) -> None:
        by_match: dict[str, list] = defaultdict(list)
        for r in results:
            if isinstance(r, StatsMessage | Cue):
                by_match[r.match_id].append(r)
        emitted = self.now()
        for match_id, items in by_match.items():
            batch = self.producer.create_batch(partition_key=match_id)
            for r in items:
                data = self.event_data(r.model_dump_json())
                data.properties = {"type": "cue" if isinstance(r, Cue) else "stats",
                                   "kind": r.kind, "match_id": match_id, "emitted_at": emitted}
                try:
                    batch.add(data)
                except ValueError:  # batch full: send it and start the next one
                    self.producer.send_batch(batch)
                    batch = self.producer.create_batch(partition_key=match_id)
                    batch.add(data)
            self.producer.send_batch(batch)

    def flush(self) -> None:
        pass


class CosmosMetricsSink:
    def __init__(self, container) -> None:
        self.container = container

    def write(self, results: list[Shared]) -> None:
        for r in results:
            if isinstance(r, MetricDoc):
                self.container.upsert_item({**r.model_dump(mode="json"), "doc_type": r.type})

    def flush(self) -> None:
        pass
