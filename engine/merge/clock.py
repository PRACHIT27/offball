"""Clock alignment (ingestion LLD §6.3): estimate feed A's clock offset against feed B.

Anchors pair a feed A event time with the moment feed B shows it:
- kickoff: the period's first pass vs the last frame the ball sat on the centre spot;
- pass: the pass time vs the frame near the pass location where the ball's speed jumps most,
  searched within ±3 s.
The offset is the rolling median of the last 30 anchor differences (A − B).
"""

from collections import deque
from statistics import median

import numpy as np

from ingest.clean import FRAME_MS, CleanEvent, CleanFrame

WINDOW_MS = 3_000
HISTORY_MS = 20_000
MEDIAN_OF = 30
NEAR_M = 2.5
MIN_JUMP_MS = 6.0  # m/s
LAG = 4  # frames either side when measuring speed (160 ms)
CENTRE = (52.5, 34.0)
STILL_M, MOVED_M = 0.3, 1.0


class ClockAligner:
    def __init__(self) -> None:
        self.anchors: deque[int] = deque(maxlen=MEDIAN_OF)
        # period → recent (frame, clock_ms, ball x, ball y)
        self.history: dict[int, deque] = {}
        self.latest_ms: dict[int, int] = {}
        # Kickoff: period → clock of the last still frame on the centre spot, and the result
        self.still_ms: dict[int, int | None] = {}
        self.b_kickoff_ms: dict[int, int] = {}
        self.a_kickoff_ms: dict[int, int] = {}
        # Passes waiting for frames up to raw time + 3 s: (period, raw_ms, x, y)
        self.pending: list[tuple[int, int, float, float]] = []

    @property
    def ready(self) -> bool:
        return bool(self.anchors)

    @property
    def offset_ms(self) -> int:
        return round(median(self.anchors)) if self.anchors else 0

    # ---------- inputs ----------

    def on_event(self, ev: CleanEvent) -> None:
        """Feed A event at its raw (unaligned) clock."""
        if ev.type != "pass" or ev.start is None or "feed_a" not in ev.source_ids:
            return
        from_centre = float(np.hypot(ev.start.x - CENTRE[0], ev.start.y - CENTRE[1]))
        if ev.period not in self.a_kickoff_ms and from_centre <= NEAR_M:
            self.a_kickoff_ms[ev.period] = ev.match_clock_ms
            self._kickoff_anchor(ev.period)
        else:
            self.pending.append((ev.period, ev.match_clock_ms, ev.start.x, ev.start.y))

    def on_frames(self, period: int, frames: list[CleanFrame]) -> None:
        hist = self.history.setdefault(period, deque())
        for f in frames:
            hist.append((f.frame, f.match_clock_ms, f.ball.x, f.ball.y))
            self._watch_kickoff(period, f)
        self.latest_ms[period] = max(self.latest_ms.get(period, -1), frames[-1].match_clock_ms)
        while hist and hist[0][1] < self.latest_ms[period] - HISTORY_MS:
            hist.popleft()
        self._resolve()

    # ---------- kickoff ----------

    def _watch_kickoff(self, period: int, f: CleanFrame) -> None:
        if period in self.b_kickoff_ms:
            return
        d = float(np.hypot(f.ball.x - CENTRE[0], f.ball.y - CENTRE[1]))
        if d <= STILL_M:
            self.still_ms[period] = f.match_clock_ms
        elif d >= MOVED_M and self.still_ms.get(period) is not None:
            self.b_kickoff_ms[period] = self.still_ms[period]
            self._kickoff_anchor(period)

    def _kickoff_anchor(self, period: int) -> None:
        if period in self.a_kickoff_ms and period in self.b_kickoff_ms:
            self.anchors.append(self.a_kickoff_ms[period] - self.b_kickoff_ms[period])

    # ---------- passes ----------

    def _resolve(self) -> None:
        still = []
        for p in self.pending:
            period, raw_ms, _, _ = p
            expected = raw_ms - self.offset_ms
            later_period = any(q > period for q in self.latest_ms)
            if self.latest_ms.get(period, -1) >= expected + WINDOW_MS + LAG * FRAME_MS \
                    or later_period:
                self._pass_anchor(*p)
            else:
                still.append(p)
        self.pending = still

    def _pass_anchor(self, period: int, raw_ms: int, x: float, y: float) -> None:
        expected = raw_ms - self.offset_ms
        rows = [h for h in self.history.get(period, ())
                if expected - WINDOW_MS - LAG * FRAME_MS <= h[1] <= expected + WINDOW_MS
                + LAG * FRAME_MS]
        if len(rows) < 2 * LAG + 1:
            return
        a = np.array(rows, dtype=float)
        frame, clock, pos = a[:, 0], a[:, 1], a[:, 2:4]
        k = np.arange(LAG, len(a) - LAG)
        contiguous = (frame[k + LAG] - frame[k - LAG]) == 2 * LAG
        dt = LAG * FRAME_MS / 1000
        v_after = np.linalg.norm(pos[k + LAG] - pos[k], axis=1) / dt
        v_before = np.linalg.norm(pos[k] - pos[k - LAG], axis=1) / dt
        near = np.linalg.norm(pos[k] - [x, y], axis=1) <= NEAR_M
        in_window = np.abs(clock[k] - expected) <= WINDOW_MS
        jump = np.where(contiguous & near & in_window, v_after - v_before, -np.inf)
        best = int(np.argmax(jump))
        if jump[best] >= MIN_JUMP_MS:
            self.anchors.append(raw_ms - int(clock[k[best]]))

    # ---------- restart ----------

    def to_state(self) -> dict:
        return {
            "anchors": list(self.anchors),
            "history": {p: list(h) for p, h in self.history.items()},
            "latest_ms": self.latest_ms,
            "still_ms": self.still_ms,
            "b_kickoff_ms": self.b_kickoff_ms,
            "a_kickoff_ms": self.a_kickoff_ms,
            "pending": self.pending,
        }

    @classmethod
    def from_state(cls, s: dict) -> "ClockAligner":
        c = cls()
        c.anchors.extend(s["anchors"])
        c.history = {int(p): deque(tuple(r) for r in h) for p, h in s["history"].items()}
        for name in ("latest_ms", "still_ms", "b_kickoff_ms", "a_kickoff_ms"):
            setattr(c, name, {int(p): v for p, v in s[name].items()})
        c.pending = [tuple(p) for p in s["pending"]]
        return c
