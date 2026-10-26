"""Local mode (FR-29): run normalizers and the merge stage over feed files, no Azure."""

import heapq
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from engine.merge.outputs import MergeOutput
from engine.merge.stage import MergeStage, parse_wall
from ingest.normalize import DeadLetter, normalize_a, normalize_b
from ingest.teamsheet import TeamSheet

FEEDS = {"A": "feed_a.jsonl", "B": "feed_b.jsonl"}


@dataclass
class RawMessage:
    feed: str
    body: str
    properties: dict
    wall_ms: float


def read_feed(path: Path, feed: str) -> Iterator[RawMessage]:
    with path.open() as f:
        for line in f:
            rec = json.loads(line)
            props = rec["properties"]
            yield RawMessage(feed, rec["body"], props, parse_wall(props["emitted_at"]))


def messages(feeds_dir: Path) -> Iterator[RawMessage]:
    """Both feeds interleaved by emitted_at, as Event Hubs would deliver them."""
    streams = [read_feed(feeds_dir / name, feed) for feed, name in FEEDS.items()
               if (feeds_dir / name).exists()]
    yield from heapq.merge(*streams, key=lambda m: m.wall_ms)


@dataclass
class Pipeline:
    match_id: str
    stage: MergeStage = None
    teamsheet: TeamSheet | None = None
    dead_letters: list[DeadLetter] = field(default_factory=list)

    def __post_init__(self):
        self.stage = self.stage or MergeStage(self.match_id)

    def process(self, msg: RawMessage) -> list[MergeOutput]:
        normalize = normalize_a if msg.feed == "A" else normalize_b
        result = normalize(msg.body, msg.properties, self.teamsheet, msg.properties["emitted_at"])
        self.teamsheet = result.teamsheet or self.teamsheet
        self.dead_letters += result.dead_letters
        self.stage.counts["rejects"] += len(result.dead_letters)
        out: list[MergeOutput] = []
        for clean in result.outputs:
            out += self.stage.handle(clean, msg.wall_ms)
        return out


def run(feeds_dir: Path, match_id: str) -> tuple[list[MergeOutput], Pipeline]:
    pipe = Pipeline(match_id)
    out: list[MergeOutput] = []
    last = 0.0
    for msg in messages(feeds_dir):
        out += pipe.process(msg)
        last = msg.wall_ms
    out += pipe.stage.flush(last)
    return out, pipe
