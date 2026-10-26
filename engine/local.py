"""Local mode (FR-29): run normalizers and the merge stage over feed files, no Azure.

    python -m engine.local --feeds local_feeds/fx01/feeds --out local_out --match fx01

Writes Silver to --out (see engine/store_local.py) and checkpoints so a killed run resumes
where it left off without losing or doubling anything (FR-27).
"""

import argparse
import heapq
import json
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from engine.merge.outputs import MergeOutput
from engine.merge.stage import MergeStage, parse_wall
from engine.store_local import LocalStore
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


# ---------- runner with storage and checkpoints ----------


def checkpoint_path(out_dir: Path, match_id: str) -> Path:
    return out_dir / "checkpoints" / f"{match_id}.json"


def _save_checkpoint(path: Path, position: int, pipe: Pipeline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "position": position,
        "stage": pipe.stage.to_state(),
        "teamsheet": pipe.teamsheet.model_dump() if pipe.teamsheet else None,
    }))
    tmp.replace(path)


def _load_pipeline(path: Path, match_id: str) -> tuple[Pipeline, int]:
    if not path.exists():
        return Pipeline(match_id), 0
    ck = json.loads(path.read_text())
    sheet = TeamSheet.model_validate(ck["teamsheet"]) if ck["teamsheet"] else None
    return Pipeline(match_id, MergeStage.from_state(ck["stage"]), sheet), ck["position"]


@dataclass
class RunResult:
    processed: int
    finished: bool
    store: LocalStore
    counts: dict


def run_local(feeds_dir: Path, out_dir: Path, match_id: str, checkpoint_every: int = 2_000,
              stop_after: int | None = None) -> RunResult:
    """Process feed files into Silver, resuming from the last checkpoint if there is one.

    `stop_after` simulates a crash: processing stops after that many messages without the final
    flush, so only what the last checkpoint saved survives.
    """
    store = LocalStore(out_dir, match_id)
    ck = checkpoint_path(out_dir, match_id)
    pipe, position = _load_pipeline(ck, match_id)
    processed, last_wall = position, 0.0
    for i, msg in enumerate(messages(feeds_dir)):
        if i < position:
            continue
        store.write(pipe.process(msg))
        for dl in pipe.dead_letters:
            store.dead_letter(dl)
        pipe.dead_letters.clear()
        processed, last_wall = i + 1, msg.wall_ms
        if stop_after is not None and processed >= stop_after:
            return RunResult(processed, False, store, dict(pipe.stage.counts))
        if processed % checkpoint_every == 0:
            store.flush()
            _save_checkpoint(ck, processed, pipe)
    store.write(pipe.stage.flush(last_wall))
    counts = dict(pipe.stage.counts) | {"clock_offset_ms": pipe.stage.offset_ms,
                                        "messages": processed}
    store.flush(counts)
    _save_checkpoint(ck, processed, pipe)
    return RunResult(processed, True, store, counts)


def main() -> None:
    ap = argparse.ArgumentParser(description="OffBall ingestion in local mode (no Azure)")
    ap.add_argument("--feeds", type=Path, required=True, help="folder with feed_a/feed_b.jsonl")
    ap.add_argument("--out", type=Path, default=Path("local_out"))
    ap.add_argument("--match", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=2_000)
    args = ap.parse_args()

    t0 = time.perf_counter()
    r = run_local(args.feeds, args.out, args.match, args.checkpoint_every)
    s = r.store
    latest = {}
    for doc in s.events.values():
        if doc["event_id"] not in latest or doc["version"] > latest[doc["event_id"]]["version"]:
            latest[doc["event_id"]] = doc
    print(f"match {args.match}: {r.processed} messages in {time.perf_counter() - t0:.1f} s")
    print(f"events: {len(latest)} ({sum(d['status'] == 'active' for d in latest.values())} "
          f"active), {len(s.events)} versions stored")
    print(f"frames: {len(s.read_frames())}")
    print(f"notices: {dict(Counter(n['kind'] for n in s.notices.values()))}")
    print(f"dead letters: {dict(Counter(d['stage'] for d in s.dead_letters.values()))}")
    print(f"counts: {r.counts}")
    print(f"silver: {args.out}")


if __name__ == "__main__":
    main()
