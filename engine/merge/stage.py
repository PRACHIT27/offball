"""Merge stage (ingestion LLD §6.2). One per match, stateful, runs inside the match engine.

`handle` takes one normalized message and the wall time it arrived, and returns clean outputs
for the router and the store. `to_state` / `from_state` snapshot everything for restarts.
"""

import heapq
from collections import Counter
from datetime import UTC, datetime, timedelta

from engine.merge.clock import ClockAligner
from engine.merge.frames import FrameTrack
from engine.merge.health import FeedHealth
from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, MergeOutput, Notice, Prematch
from ingest.clean import (
    CleanEvent,
    NormalizedDelete,
    NormalizedEvent,
    NormalizedFrames,
    NormalizedMessage,
    NormalizedPrematch,
)

WAIT_MS = 1_500
# Before the first clock anchor, feed A events wait up to this long for one
FIRST_ANCHOR_WAIT_MS = 10_000
DEDUPE_WINDOW_MS = 300_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
EVENT_NOTICES = {"conditions": "conditions.changed", "stoppage_start": "stoppage.start",
                 "stoppage_end": "stoppage.end"}


def parse_wall(iso: str) -> float:
    """ISO 8601 UTC → milliseconds since the epoch."""
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) - EPOCH) / timedelta(milliseconds=1)


def wall_iso(ms: float) -> str:
    t = EPOCH + timedelta(milliseconds=round(ms))
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class MergeStage:
    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        # Highest version seen per event (deleted ones included)
        self.latest: dict[str, CleanEvent] = {}
        # Deletions that arrived before their event
        self.tombstones: dict[str, int] = {}
        self.released: set[str] = set()
        # Wait window: (period, raw clock ms, seq, event_id, version)
        self.buffer: list[tuple[int, int, int, str, int]] = []
        self.seq = 0
        # Dedupe keys → wall ms first seen, kept for 5 minutes
        self.seen: dict[str, float] = {}
        self.watermark: tuple[int, int] = (0, -1)
        self.frames = FrameTrack()
        self.clock = ClockAligner()
        self.health = FeedHealth()
        self.counts: Counter = Counter()

    # ---------- clock ----------

    @property
    def offset_ms(self) -> int:
        """Current feed A clock offset estimate (FR-14), applied when events are released."""
        return self.clock.offset_ms

    def _aligned(self, ev: CleanEvent, now: str) -> CleanEvent:
        shift = self.offset_ms if "feed_a" in ev.source_ids else 0
        clock = ev.match_clock_ms - shift
        return ev.model_copy(update={"match_clock_ms": clock,
                                     "timings": {**ev.timings, "merged_at": now}})

    def _advance(self, period: int, clock_ms: int) -> None:
        self.watermark = max(self.watermark, (period, clock_ms))

    # ---------- entry points ----------

    def handle(self, msg: NormalizedMessage, wall_ms: float) -> list[MergeOutput]:
        now = wall_iso(wall_ms)
        self._expire(wall_ms)
        if isinstance(msg, NormalizedFrames):
            self.health.period_seen(msg.batch.period)
        elif isinstance(msg, NormalizedEvent) and msg.event.type == "period_start":
            self.health.period_seen(msg.event.period)
        elif isinstance(msg, NormalizedEvent) and msg.event.type == "period_end":
            self.health.period_ended(msg.event.period)
        health = self.health.on_message("B" if isinstance(msg, NormalizedFrames) else "A", wall_ms)
        match msg:
            case NormalizedPrematch():
                out = [Prematch(match_id=msg.match_id, prematch=msg.prematch)]
            case NormalizedFrames():
                out = self._frames(msg, now)
            case NormalizedEvent():
                out = self._event(msg.event, wall_ms, now)
            case NormalizedDelete():
                out = self._delete(msg, wall_ms, now)
        return self._health_notices(health) + out + self._release(now)

    def tick(self, wall_ms: float) -> list[MergeOutput]:
        """Timer hook for the engine: feed health is checked even when nothing arrives."""
        return self._health_notices(self.health.tick(wall_ms))

    def _health_notices(self, found: list[dict]) -> list[MergeOutput]:
        self.counts["feed_stopped"] += sum(n["kind"] == "notice.feed_stopped" for n in found)
        period, clock = self.watermark
        return [Notice(kind=n["kind"], notice_id=f"{n['kind']}:{n['feed']}:{round(n['wall_ms'])}",
                       match_id=self.match_id, period=period or None,
                       match_clock_ms=clock if period else None, details=n["details"],
                       emitted_at=wall_iso(n["wall_ms"]))
                for n in found]

    def flush(self, wall_ms: float) -> list[MergeOutput]:
        """Release everything still in the wait window (end of stream, or a long quiet spell).

        The watermark is left alone, so events that arrive afterwards are ordered as usual.
        """
        held = self.watermark
        self.watermark = (99, 0)
        try:
            return self._release(wall_iso(wall_ms))
        finally:
            self.watermark = held

    # ---------- events ----------

    def _dedupe(self, key: str, wall_ms: float) -> bool:
        if key in self.seen:
            self.counts["duplicates"] += 1
            return True
        self.seen[key] = wall_ms
        return False

    def _expire(self, wall_ms: float) -> None:
        if len(self.seen) > 2_000:
            cutoff = wall_ms - DEDUPE_WINDOW_MS
            self.seen = {k: t for k, t in self.seen.items() if t >= cutoff}

    def _event(self, ev: CleanEvent, wall_ms: float, now: str) -> list[MergeOutput]:
        if self._dedupe(f"E:{ev.event_id}:{ev.version}", wall_ms):
            return []
        prev = self.latest.get(ev.event_id)
        if (prev and ev.version <= prev.version) or ev.version <= self.tombstones.get(
                ev.event_id, 0):
            self.counts["stale_versions"] += 1
            return []
        self.latest[ev.event_id] = ev
        if prev is None:
            self.clock.on_event(ev)

        if ev.event_id in self.released:
            # Late correction of an event already handed on (FR-17, FR-19)
            self.counts["corrections"] += 1
            clean = self._aligned(ev, now)
            return [EventUpsert(event=clean), self._notice(
                "notice.correction_applied", clean, now,
                {"event_id": ev.event_id, "version": ev.version, "action": "upsert"})]
        if prev:
            self.counts["corrections"] += 1  # replaced while still in the wait window

        key = (ev.period, ev.match_clock_ms - self.offset_ms)
        if (key[0], key[1] + WAIT_MS) < self.watermark:
            # Arrived after its wait window closed: release now as a late insert (FR-13)
            self.counts["late_inserts"] += 1
            self.released.add(ev.event_id)
            return self._publish(ev, now, late=True)
        heapq.heappush(self.buffer, (ev.period, ev.match_clock_ms, self.seq, ev.event_id,
                                     ev.version))
        self.seq += 1
        self._advance(*key)
        return []

    def _delete(self, d: NormalizedDelete, wall_ms: float, now: str) -> list[MergeOutput]:
        if self._dedupe(f"D:{d.event_id}:{d.version}", wall_ms):
            return []
        prev = self.latest.get(d.event_id)
        if prev is None:
            self.tombstones[d.event_id] = max(d.version, self.tombstones.get(d.event_id, 0))
            return []
        if d.version <= prev.version:
            self.counts["stale_versions"] += 1
            return []
        deleted = prev.model_copy(update={
            "version": d.version, "status": "deleted", "emitted_at": d.emitted_at,
            "timings": d.timings})
        self.latest[d.event_id] = deleted
        self.counts["deletions"] += 1
        was_released = d.event_id in self.released
        self.released.add(d.event_id)
        clean = self._aligned(deleted, now)
        out: list[MergeOutput] = [EventDelete(event=clean)]
        if was_released:
            out.append(self._notice("notice.correction_applied", clean, now,
                                    {"event_id": d.event_id, "version": d.version,
                                     "action": "delete"}))
        return out

    def _release(self, now: str) -> list[MergeOutput]:
        out: list[MergeOutput] = []
        while self.buffer:
            period, raw_ms, _, event_id, version = self.buffer[0]
            wait = WAIT_MS if self.clock.ready else FIRST_ANCHOR_WAIT_MS
            if (period, raw_ms - self.offset_ms + wait) > self.watermark:
                break
            heapq.heappop(self.buffer)
            ev = self.latest[event_id]
            if ev.version != version or ev.status == "deleted" or event_id in self.released:
                continue  # superseded while waiting
            self.released.add(event_id)
            out += self._publish(ev, now, late=False)
        return out

    def _publish(self, ev: CleanEvent, now: str, late: bool) -> list[MergeOutput]:
        clean = self._aligned(ev, now)
        out: list[MergeOutput] = [EventUpsert(event=clean, late=late)]
        if ev.type in EVENT_NOTICES:
            out.append(self._notice(EVENT_NOTICES[ev.type], clean, now, ev.details or {}))
        return out

    def _notice(self, kind: str, ev: CleanEvent, now: str, details: dict) -> Notice:
        return Notice(kind=kind, notice_id=f"{kind}:{ev.event_id}:{ev.version}",
                      match_id=self.match_id, period=ev.period, match_clock_ms=ev.match_clock_ms,
                      details=details, emitted_at=now)

    # ---------- frames ----------

    def _frames(self, msg: NormalizedFrames, now: str) -> list[MergeOutput]:
        batch, counts, gaps = self.frames.handle(msg.batch)
        self.counts.update(counts)
        if batch is None:
            return []
        self.clock.on_frames(batch.period, batch.frames)
        last = batch.frames[-1]
        self._advance(batch.period, last.match_clock_ms)
        notices: list[MergeOutput] = [
            Notice(kind=g["kind"], notice_id=f"{g['kind']}:{batch.period}:{g['frame']}",
                   match_id=self.match_id, period=batch.period,
                   match_clock_ms=g["match_clock_ms"], details=g["details"], emitted_at=now)
            for g in gaps]
        return notices + [FramesOut(batch=batch.model_copy(
            update={"timings": {**batch.timings, "merged_at": now}}))]

    # ---------- restart ----------

    def to_state(self) -> dict:
        return {
            "match_id": self.match_id,
            "latest": {k: v.model_dump(mode="json") for k, v in self.latest.items()},
            "tombstones": self.tombstones,
            "released": sorted(self.released),
            "buffer": self.buffer,
            "seq": self.seq,
            "seen": self.seen,
            "watermark": list(self.watermark),
            "frames": self.frames.to_state(),
            "clock": self.clock.to_state(),
            "health": self.health.to_state(),
            "counts": dict(self.counts | {"clock_offset_ms": self.offset_ms}),
        }

    @classmethod
    def from_state(cls, state: dict) -> "MergeStage":
        m = cls(state["match_id"])
        m.latest = {k: CleanEvent.model_validate(v) for k, v in state["latest"].items()}
        m.tombstones = state["tombstones"]
        m.released = set(state["released"])
        m.buffer = [tuple(b) for b in state["buffer"]]
        heapq.heapify(m.buffer)
        m.seq = state["seq"]
        m.seen = state["seen"]
        m.watermark = tuple(state["watermark"])
        m.frames = FrameTrack.from_state(state["frames"])
        m.clock = ClockAligner.from_state(state["clock"])
        m.health = FeedHealth.from_state(state["health"])
        m.counts = Counter(state["counts"])
        return m
