"""Feed health (LLD §6.4): announce when one feed goes quiet while the other keeps sending.

Only judged while the ball is in play (period start to period end), so half-time and full-time
raise nothing.

Feed B (25 Hz tracking) is flagged after 3 s of silence, as the LLD says. Feed A only sends
when something happens and is naturally quiet for 20–45 s after goals and during stoppages, so
it is flagged after 60 s instead.
"""

SILENCE_MS = {"A": 60_000, "B": 3_000}


class FeedHealth:
    def __init__(self) -> None:
        # Highest period that has ended; nothing is judged until the next period starts
        self.ended_period = 0
        self.in_play = True
        self.last: dict[str, float] = {}
        # When each feed's current run of activity began
        self.active_since: dict[str, float] = {}
        self.stopped: set[str] = set()

    def period_ended(self, period: int) -> None:
        self.ended_period = max(self.ended_period, period)
        self.in_play = False

    def period_seen(self, period: int) -> None:
        if period > self.ended_period:
            self.in_play = True

    def on_message(self, feed: str, wall_ms: float) -> list[dict]:
        out = []
        prev = self.last.get(feed)
        if feed in self.stopped:
            self.stopped.discard(feed)
            out.append({"kind": "notice.feed_resumed", "feed": feed, "wall_ms": wall_ms,
                        "details": {"feed": feed, "silent_ms": round(wall_ms - prev)}})
        if prev is None or wall_ms - prev > SILENCE_MS[feed]:
            self.active_since[feed] = wall_ms
        self.last[feed] = wall_ms
        return out + self.tick(wall_ms, active=feed)

    def tick(self, wall_ms: float, active: str | None = None) -> list[dict]:
        """Check for stopped feeds. The engine also calls this on a timer."""
        out = []
        if not self.in_play:
            return out
        for feed, other in (("A", "B"), ("B", "A")):
            if active not in (None, other) or other not in self.active_since:
                continue
            seen = self.last.get(feed)
            # Only judge a feed that was sending during the other's current run of activity
            if (feed in self.stopped or seen is None or seen < self.active_since[other]
                    or wall_ms - seen <= SILENCE_MS[feed]):
                continue
            self.stopped.add(feed)
            out.append({"kind": "notice.feed_stopped", "feed": feed, "wall_ms": wall_ms,
                        "details": {"feed": feed, "last_seen_ms": round(seen)}})
        return out

    def to_state(self) -> dict:
        return {"ended_period": self.ended_period, "in_play": self.in_play, "last": self.last,
                "active_since": self.active_since, "stopped": sorted(self.stopped)}

    @classmethod
    def from_state(cls, s: dict) -> "FeedHealth":
        h = cls()
        h.ended_period, h.in_play = s["ended_period"], s["in_play"]
        h.last, h.active_since, h.stopped = s["last"], s["active_since"], set(s["stopped"])
        return h
