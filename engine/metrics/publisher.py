"""Publisher (LLD §4): sends every result to the screen (`stats`), Broadcast (cues), Cosmos
(`metrics`) and Tactical Intelligence (direct call). Results already carry their evidence."""

import json
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from engine.metrics.models import (
    Cue,
    MetricDoc,
    MetricsOutput,
    PassValues,
    PressureSample,
    StatsMessage,
)

# Built on by Tactical Intelligence: register a callback here to receive PressureSample (every
# frame) and PassValues (every pass, again on correction or deletion) in-process.
ToTactics = Callable[[PressureSample | PassValues], None]
Shared = StatsMessage | Cue | MetricDoc


class Sink(Protocol):
    def write(self, results: list[Shared]) -> None: ...
    def flush(self) -> None: ...


class Publisher:
    def __init__(self, sinks: Iterable[Sink] = (), to_tactics: Iterable[ToTactics] = ()) -> None:
        self.sinks = list(sinks)
        self.to_tactics = list(to_tactics)
        self.counts: Counter = Counter()

    def emit(self, results: Iterable[MetricsOutput]) -> None:
        shared: list[Shared] = []
        for r in results:
            match r:
                case StatsMessage():
                    self.counts[f"stats.{r.kind}"] += 1
                    shared.append(r)
                case Cue():
                    self.counts[f"cue.{r.kind}.{r.status}"] += 1
                    shared.append(r)
                case MetricDoc():
                    self.counts[f"metric.{r.type}"] += 1
                    shared.append(r)
                case PressureSample() | PassValues():
                    self.counts[f"tactics.{r.kind}"] += 1
                    for call in self.to_tactics:
                        call(r)
        if shared:
            for s in self.sinks:
                s.write(shared)

    def flush(self) -> None:
        for s in self.sinks:
            s.flush()


class LocalSink:
    """Local mode (PM-28): `stats.jsonl` and `cues.jsonl` as sent, `metrics.json` as Cosmos would
    hold it (upsert by id)."""

    def __init__(self, out_dir: Path, match_id: str) -> None:
        self.dir = out_dir / "metrics" / match_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._stats = (self.dir / "stats.jsonl").open("w")
        self._cues = (self.dir / "cues.jsonl").open("w")
        self.metrics: dict[str, dict] = {}

    def write(self, results: list[Shared]) -> None:
        for r in results:
            match r:
                case StatsMessage():
                    self._stats.write(r.model_dump_json() + "\n")
                case Cue():
                    self._cues.write(r.model_dump_json() + "\n")
                case MetricDoc():
                    self.metrics[r.id] = r.model_dump(mode="json")

    def flush(self) -> None:
        self._stats.flush()
        self._cues.flush()
        tmp = self.dir / "metrics.tmp"
        tmp.write_text(json.dumps(self.metrics, separators=(",", ":")))
        tmp.replace(self.dir / "metrics.json")

    def close(self) -> None:
        self.flush()
        self._stats.close()
        self._cues.close()
