"""Rolling frame memory (LLD §7: last 10 s, in memory only) and the player roster.

Raw and smoothed positions live in fixed NumPy rings with one column per player. Smoothing is a
centred 5-frame moving average, so frame k is smoothed once frame k + 2 has arrived. It never
crosses a gap in the frames, nor a jump in one player's position (a new track segment).
"""

import warnings
from dataclasses import dataclass

import numpy as np

from ingest.clean import FRAME_MS, CleanFrame

DT = FRAME_MS / 1000
CAPACITY = 256  # > 10 s at 25 Hz
MAX_PLAYERS = 64
HALF_WINDOW = 2  # centred 5 frames
SPEED_SPAN = 5  # speed over smoothed positions 0.2 s apart
# Faster than any footballer: a tracking glitch or a jump in position, not running
MAX_PLAUSIBLE_MS = 12.0
JUMP_M = MAX_PLAUSIBLE_MS * DT


class Roster:
    """player_id ↔ column, and each player's team (from the ID prefix, e.g. RIV-07 → RIV)."""

    def __init__(self, home_id: str | None = None) -> None:
        self.home_id = home_id
        self.ids: list[str] = []
        self.teams: list[str] = []
        self.col: dict[str, int] = {}

    def column(self, player_id: str) -> int:
        c = self.col.get(player_id)
        if c is None:
            if len(self.ids) >= MAX_PLAYERS:
                raise ValueError(f"more than {MAX_PLAYERS} players seen")
            c = self.col[player_id] = len(self.ids)
            self.ids.append(player_id)
            self.teams.append(team_of(player_id))
        return c

    def team_cols(self, team: str) -> np.ndarray:
        return np.array([i for i, t in enumerate(self.teams) if t == team], dtype=int)

    def to_state(self) -> dict:
        return {"home_id": self.home_id, "ids": self.ids}

    @classmethod
    def from_state(cls, state: dict) -> "Roster":
        r = cls(state["home_id"])
        for pid in state["ids"]:
            r.column(pid)
        return r


def team_of(player_id: str) -> str:
    return player_id.split("-", 1)[0]


@dataclass
class Window:
    """Frames in time order, columns as in the roster."""

    frame: np.ndarray
    clock: np.ndarray
    ball: np.ndarray  # (n, 3)
    pos: np.ndarray  # (n, MAX_PLAYERS, 2), NaN when off the pitch
    ball_speed: np.ndarray  # (n,), NaN when not smoothed yet
    speed: np.ndarray  # (n, MAX_PLAYERS)
    smooth_pos: np.ndarray  # (n, MAX_PLAYERS, 2)


class FrameMemory:
    def __init__(self, roster: Roster) -> None:
        self.roster = roster
        self.period: int | None = None
        self.reset()

    def reset(self) -> None:
        self.n = 0
        # First index of the current run of consecutive frames (smoothing never crosses a gap)
        self.run_start = 0
        self.last_frame: int | None = None
        self.frame = np.zeros(CAPACITY, dtype=np.int64)
        self.clock = np.zeros(CAPACITY, dtype=np.int64)
        self.ball = np.full((CAPACITY, 3), np.nan)
        self.pos = np.full((CAPACITY, MAX_PLAYERS, 2), np.nan)
        self.s_ball = np.full((CAPACITY, 3), np.nan)
        self.s_pos = np.full((CAPACITY, MAX_PLAYERS, 2), np.nan)
        self.ball_speed = np.full(CAPACITY, np.nan)
        self.speed = np.full((CAPACITY, MAX_PLAYERS), np.nan)
        # Track segment per player: changes when a player appears or jumps
        self.seg = np.zeros((CAPACITY, MAX_PLAYERS), dtype=np.int64)
        self.seg_count = np.zeros(MAX_PLAYERS, dtype=np.int64)
        # Highest index whose smoothed values are final
        self.smoothed_to = -1

    # ---------- writes ----------

    def append(self, period: int, f: CleanFrame) -> int:
        """Store one raw frame; returns its index, or -1 if it is old or repeated."""
        if period != self.period:
            self.period = period
            self.reset()
        if self.last_frame is not None and f.frame <= self.last_frame:
            return -1
        if self.last_frame is not None and f.frame != self.last_frame + 1:
            self.run_start = self.n
        i, s = self.n, self.n % CAPACITY
        prev = self.pos[(i - 1) % CAPACITY].copy() if i > self.run_start else None
        self.frame[s], self.clock[s] = f.frame, f.match_clock_ms
        self.ball[s] = (f.ball.x, f.ball.y, f.ball.z)
        self.pos[s] = np.nan
        for p in f.players:
            self.pos[s, self.roster.column(p.player_id)] = (p.x, p.y)
        here = ~np.isnan(self.pos[s]).any(axis=1)
        if prev is None:
            self.seg_count[here] += 1
        else:
            with np.errstate(invalid="ignore"):
                jump = ~(np.linalg.norm(self.pos[s] - prev, axis=1) <= JUMP_M)
            self.seg_count[here & jump] += 1
        self.seg[s] = self.seg_count
        self.s_ball[s], self.s_pos[s] = np.nan, np.nan
        self.ball_speed[s], self.speed[s] = np.nan, np.nan
        self.last_frame = f.frame
        self.n += 1
        return i

    def smooth_ready(self) -> list[int]:
        """Smooth every frame that now has its 2 later neighbours; returns their indices."""
        done = []
        for k in range(max(self.smoothed_to + 1, self.run_start, self.n - CAPACITY + 4),
                       self.n - HALF_WINDOW):
            self._smooth(k)
            done.append(k)
            self.smoothed_to = k
        return done

    def _smooth(self, k: int) -> None:
        lo = max(self.run_start if k >= self.run_start else 0, k - HALF_WINDOW)
        idx = [j % CAPACITY for j in range(lo, k + HALF_WINDOW + 1)]
        s = k % CAPACITY
        same = self.seg[idx] == self.seg[s]  # (w, players): same track segment as frame k
        with warnings.catch_warnings():
            # Mean of an empty slice: a player off the pitch for the whole window
            warnings.simplefilter("ignore", RuntimeWarning)
            self.s_ball[s] = np.nanmean(self.ball[idx], axis=0)
            sp = np.nanmean(np.where(same[..., None], self.pos[idx], np.nan), axis=0)
        sp[np.isnan(self.pos[s]).any(axis=1)] = np.nan  # off the pitch at frame k
        self.s_pos[s] = sp
        j0 = max(self.run_start, k - SPEED_SPAN)
        if j0 < k:
            js = [j % CAPACITY for j in range(j0, k)]
            self.ball_speed[s] = np.linalg.norm(self.s_ball[s] - self.s_ball[js[0]]) / (
                (k - j0) * DT)
            # Per player, the earliest frame in the span on the same track segment
            match = self.seg[js] == self.seg[s]
            first = np.argmax(match, axis=0)
            cols = np.arange(MAX_PLAYERS)
            back = self.s_pos[np.array(js)[first], cols]
            with np.errstate(invalid="ignore", divide="ignore"):
                speed = np.linalg.norm(sp - back, axis=1) / ((k - j0 - first) * DT)
            speed[~match.any(axis=0) | ~(speed <= MAX_PLAUSIBLE_MS)] = np.nan
            self.speed[s] = speed

    # ---------- reads ----------

    def slot(self, k: int) -> int:
        return k % CAPACITY

    def oldest(self) -> int:
        return max(0, self.n - CAPACITY)

    def latest_smoothed_clock(self) -> int | None:
        return int(self.clock[self.smoothed_to % CAPACITY]) if self.smoothed_to >= 0 else None

    def latest_clock(self) -> int | None:
        return int(self.clock[(self.n - 1) % CAPACITY]) if self.n else None

    def window(self, period: int, from_ms: int, to_ms: int) -> Window | None:
        """Frames with from_ms ≤ clock ≤ to_ms still in memory, in time order."""
        if period != self.period or not self.n:
            return None
        order = np.arange(self.oldest(), self.n) % CAPACITY
        clocks = self.clock[order]
        sel = order[(clocks >= from_ms) & (clocks <= to_ms)]
        if not len(sel):
            return None
        return Window(self.frame[sel], self.clock[sel], self.ball[sel], self.pos[sel],
                      self.ball_speed[sel], self.speed[sel], self.s_pos[sel])

    def nearest_index(self, period: int, clock_ms: int) -> int | None:
        """Ring slot of the frame closest in time, if within one frame of `clock_ms`."""
        if period != self.period or not self.n:
            return None
        order = np.arange(self.oldest(), self.n) % CAPACITY
        d = np.abs(self.clock[order] - clock_ms)
        j = int(np.argmin(d))
        return int(order[j]) if d[j] <= FRAME_MS else None

