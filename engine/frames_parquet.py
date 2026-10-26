"""Silver frames as Parquet: one file per match per period per 5 minutes (LLD §8)."""

import io

import pyarrow as pa
import pyarrow.parquet as pq

from engine.merge.outputs import FramesOut
from ingest.clean import PERIOD_BASE_MS, CleanFrame

CHUNK_MS = 300_000

SCHEMA = pa.schema([
    ("frame", pa.int32()), ("match_clock_ms", pa.int64()), ("period", pa.int8()),
    ("ball_x", pa.float32()), ("ball_y", pa.float32()), ("ball_z", pa.float32()),
    ("interpolated", pa.bool_()),
    ("players", pa.list_(pa.struct([("player_id", pa.string()), ("x", pa.float32()),
                                    ("y", pa.float32())]))),
])

ChunkKey = tuple[int, int]  # (period, start_ms)


def chunk_name(match_id: str, key: ChunkKey) -> str:
    return f"{match_id}/{key[0]}/{key[1]}.parquet"


def _row(period: int, f: CleanFrame) -> dict:
    return {"frame": f.frame, "match_clock_ms": f.match_clock_ms, "period": period,
            "ball_x": f.ball.x, "ball_y": f.ball.y, "ball_z": f.ball.z,
            "interpolated": f.interpolated,
            "players": [{"player_id": p.player_id, "x": p.x, "y": p.y} for p in f.players]}


def to_bytes(rows: dict[int, dict]) -> bytes:
    buf = io.BytesIO()
    table = pa.Table.from_pylist([rows[n] for n in sorted(rows)], schema=SCHEMA)
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def from_bytes(data: bytes) -> dict[int, dict]:
    return {r["frame"]: r for r in pq.read_table(io.BytesIO(data)).to_pylist()}


class ChunkBuffer:
    """Collects frames per 5-minute chunk; a chunk is complete once a later chunk starts."""

    def __init__(self) -> None:
        self.chunks: dict[ChunkKey, dict[int, dict]] = {}

    def add(self, o: FramesOut) -> list[ChunkKey]:
        period = o.batch.period
        base = PERIOD_BASE_MS[period]
        for f in o.batch.frames:
            key = (period, base + (f.match_clock_ms - base) // CHUNK_MS * CHUNK_MS)
            self.chunks.setdefault(key, {})[f.frame] = _row(period, f)
        newest = max(self.chunks)
        return [k for k in self.chunks if k < newest]
