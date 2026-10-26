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

from engine.frames_parquet import ChunkBuffer, ChunkKey, chunk_name, from_bytes, to_bytes
from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, MergeOutput, Notice, Prematch
from ingest.normalize import DeadLetter


class LocalStore:
    def __init__(self, root: Path, match_id: str) -> None:
        self.root = root
        self.match_id = match_id
        self.events: dict[str, dict] = {}
        self.notices: dict[str, dict] = {}
        self.dead_letters: dict[str, dict] = {}
        self.prematch: dict | None = None
        self.frames = ChunkBuffer()
        self.load()

    @property
    def silver(self) -> Path:
        return self.root / "silver" / self.match_id

    def frames_path(self, key: ChunkKey) -> Path:
        return self.root / "silver-frames" / chunk_name(self.match_id, key)

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
                    for key in self.frames.add(o):
                        self._write_chunk(key)
                        del self.frames.chunks[key]

    def _write_chunk(self, key: ChunkKey) -> None:
        path = self.frames_path(key)
        # A chunk can span a restart: merge with what is already written
        rows = from_bytes(path.read_bytes()) if path.exists() else {}
        rows.update(self.frames.chunks[key])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(to_bytes(rows))
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
        for key in self.frames.chunks:
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
            rows += from_bytes(path.read_bytes()).values()
        return sorted(rows, key=lambda r: (r["period"], r["frame"]))


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
    tmp.replace(path)


def _load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default
