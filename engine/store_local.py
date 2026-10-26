"""Local Silver store (LLD §8 layout, on disk instead of Cosmos DB and Blob Storage).

Every write is an upsert on a stable key, so replays change nothing (idempotent):
- events: all versions, key `event_id:version` (Cosmos `events` on Azure)
- frames: Parquet, one file per match per period per 5 minutes, `match_id/period/start_ms`
- notices, dead letters, pre-match, counts

`flush` makes everything durable; the runner calls it at each checkpoint.
"""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, MergeOutput, Notice, Prematch
from ingest.clean import PERIOD_BASE_MS, CleanFrame
from ingest.normalize import DeadLetter

CHUNK_MS = 300_000

FRAME_SCHEMA = pa.schema([
    ("frame", pa.int32()), ("match_clock_ms", pa.int64()), ("period", pa.int8()),
    ("ball_x", pa.float32()), ("ball_y", pa.float32()), ("ball_z", pa.float32()),
    ("interpolated", pa.bool_()),
    ("players", pa.list_(pa.struct([("player_id", pa.string()), ("x", pa.float32()),
                                    ("y", pa.float32())]))),
])


def _chunk(period: int, clock_ms: int) -> tuple[int, int]:
    base = PERIOD_BASE_MS[period]
    return period, base + (clock_ms - base) // CHUNK_MS * CHUNK_MS


class LocalStore:
    def __init__(self, root: Path, match_id: str) -> None:
        self.root = root
        self.match_id = match_id
        self.events: dict[str, dict] = {}
        self.notices: dict[str, dict] = {}
        self.dead_letters: dict[str, dict] = {}
        self.prematch: dict | None = None
        # (period, start_ms) → {frame: CleanFrame}; written when complete or at flush
        self.chunks: dict[tuple[int, int], dict[int, CleanFrame]] = {}
        self.load()

    # ---------- paths ----------

    @property
    def silver(self) -> Path:
        return self.root / "silver" / self.match_id

    def frames_path(self, period: int, start_ms: int) -> Path:
        return self.root / "silver-frames" / self.match_id / str(period) / f"{start_ms}.parquet"

    # ---------- writes ----------

    def write(self, outputs: list[MergeOutput]) -> None:
        for o in outputs:
            match o:
                case EventUpsert() | EventDelete():
                    ev = o.event
                    self.events[f"{ev.event_id}:{ev.version}"] = ev.model_dump(mode="json")
                case Notice():
                    self.notices[o.notice_id] = o.model_dump(mode="json")
                case Prematch():
                    self.prematch = o.prematch
                case FramesOut():
                    self._frames(o)

    def _frames(self, o: FramesOut) -> None:
        period = o.batch.period
        for f in o.batch.frames:
            key = _chunk(period, f.match_clock_ms)
            self.chunks.setdefault(key, {})[f.frame] = f
        # A chunk is complete once frames from a later chunk arrive
        newest = max(self.chunks)
        for key in [k for k in self.chunks if k < newest]:
            self._write_chunk(key)
            del self.chunks[key]

    def _write_chunk(self, key: tuple[int, int]) -> None:
        period, start_ms = key
        path = self.frames_path(period, start_ms)
        existing = {}
        if path.exists():  # a chunk can span a restart: merge with what is already written
            for row in pq.read_table(path).to_pylist():
                existing[row["frame"]] = row
        for n, f in self.chunks[key].items():
            existing[n] = {
                "frame": f.frame, "match_clock_ms": f.match_clock_ms, "period": period,
                "ball_x": f.ball.x, "ball_y": f.ball.y, "ball_z": f.ball.z,
                "interpolated": f.interpolated,
                "players": [{"player_id": p.player_id, "x": p.x, "y": p.y} for p in f.players]}
        rows = [existing[n] for n in sorted(existing)]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        pq.write_table(pa.Table.from_pylist(rows, schema=FRAME_SCHEMA), tmp, compression="zstd")
        tmp.replace(path)

    def dead_letter(self, dl: DeadLetter) -> None:
        digest = hashlib.sha256(f"{dl.feed}|{dl.properties.get('emitted_at')}|{dl.body}".encode())
        key = f"{dl.stage}/{dl.properties.get('emitted_at')}/{digest.hexdigest()[:12]}"
        self.dead_letters[key] = dl.to_dict()

    # ---------- durability ----------

    def flush(self, counts: dict | None = None) -> None:
        self.silver.mkdir(parents=True, exist_ok=True)
        _dump(self.silver / "events.json", self.events)
        _dump(self.silver / "notices.json", self.notices)
        _dump(self.root / "dead-letter" / self.match_id / "dead_letters.json", self.dead_letters)
        if self.prematch is not None:
            _dump(self.silver / "prematch.json", self.prematch)
        if counts is not None:
            _dump(self.silver / "counts.json", counts)
        for key in self.chunks:
            self._write_chunk(key)

    def load(self) -> None:
        self.events = _load(self.silver / "events.json", {})
        self.notices = _load(self.silver / "notices.json", {})
        self.dead_letters = _load(self.root / "dead-letter" / self.match_id / "dead_letters.json",
                                  {})
        self.prematch = _load(self.silver / "prematch.json", None)

    def read_frames(self) -> list[dict]:
        rows = []
        for path in sorted((self.root / "silver-frames" / self.match_id).rglob("*.parquet")):
            rows += pq.read_table(path).to_pylist()
        return sorted(rows, key=lambda r: (r["period"], r["frame"]))


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
    tmp.replace(path)


def _load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default
