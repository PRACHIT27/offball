"""Hand-built frames and events for metrics tests. Fictional clubs only."""

from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, Prematch
from engine.metrics.router import MetricsEngine
from ingest.clean import (
    FRAME_MS,
    PERIOD_BASE_MS,
    CleanEvent,
    CleanFrame,
    CleanFrameBatch,
    PlayerPosition,
    Point,
    Point3,
)
from tests.factories import prematch

EMITTED = "2026-10-25T14:00:00.000Z"


def engine(match_id: str = "m001") -> MetricsEngine:
    e = MetricsEngine(match_id)
    e.dispatch(Prematch(match_id=match_id, prematch=prematch(match_id)))
    return e


def frame(n: int, players: dict[str, tuple[float, float]], ball=(52.5, 34.0, 0.0),
          period: int = 1) -> CleanFrame:
    return CleanFrame(frame=n, match_clock_ms=PERIOD_BASE_MS[period] + n * FRAME_MS,
                      ball=Point3(x=ball[0], y=ball[1], z=ball[2]),
                      players=[PlayerPosition(player_id=p, x=x, y=y)
                               for p, (x, y) in players.items()])


def batches(frames: list[CleanFrame], match_id: str = "m001", period: int = 1,
            size: int = 5) -> list[FramesOut]:
    return [FramesOut(batch=CleanFrameBatch(match_id=match_id, period=period,
                                            frames=frames[i:i + size], emitted_at=EMITTED))
            for i in range(0, len(frames), size)]


def clock(n: int, period: int = 1) -> int:
    return PERIOD_BASE_MS[period] + n * FRAME_MS


def event(event_id: str, type_: str, at_frame: int, player: str | None, version: int = 1,
          period: int = 1, start=None, end=None, **kw) -> CleanEvent:
    return CleanEvent(
        event_id=event_id, version=version, match_id="m001", match_clock_ms=clock(at_frame, period),
        period=period, type=type_, team_id=player.split("-")[0] if player else None,
        player_id=player, start=Point(x=start[0], y=start[1]) if start else None,
        end=Point(x=end[0], y=end[1]) if end else None, source_ids={"A": 1},
        emitted_at=EMITTED, **kw)


def upsert(ev: CleanEvent) -> EventUpsert:
    return EventUpsert(event=ev)


def delete(ev: CleanEvent) -> EventDelete:
    return EventDelete(event=ev.model_copy(update={"status": "deleted",
                                                   "version": ev.version + 1}))


def run(e: MetricsEngine, msgs) -> list:
    out = []
    for m in msgs:
        out += e.dispatch(m)
    return out
