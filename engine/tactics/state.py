from bisect import bisect_right
from dataclasses import dataclass, field

import numpy as np

from ingest.clean import CleanEvent, CleanFrameBatch

ON_BALL = {"pass", "take_on", "tackle", "interception", "clearance", "shot"}
LENGTH, WIDTH = 105.0, 68.0


class Roster:
    def __init__(self) -> None:
        self.home: str | None = None
        self.away: str | None = None
        self.ids: list[str] = []
        self.col: dict[str, int] = {}
        self.team: dict[str, str] = {}
        self.position: dict[str, str] = {}

    def load_prematch(self, prematch: dict) -> None:
        self.home = prematch["home"]["club_id"]
        self.away = prematch["away"]["club_id"]
        for side in ("home", "away"):
            for p in prematch[side]["players"]:
                self.column(p["player_id"])
                self.position[p["player_id"]] = p.get("position", "")

    def column(self, player_id: str) -> int:
        c = self.col.get(player_id)
        if c is None:
            c = self.col[player_id] = len(self.ids)
            self.ids.append(player_id)
            self.team[player_id] = player_id.split("-")[0]
        return c

    def other(self, team: str) -> str:
        return self.away if team == self.home else self.home

    def cols(self, team: str, outfield: bool = True) -> np.ndarray:
        return np.array([c for c, p in enumerate(self.ids) if self.team[p] == team
                         and not (outfield and self.position.get(p) == "GK")], dtype=int)

    def gk(self, team: str) -> str | None:
        return next((p for p in self.ids if self.team[p] == team
                     and self.position.get(p) == "GK"), None)


def depth(roster: Roster, team: str, x):
    x = np.asarray(x, dtype=float)
    return x if team == roster.home else LENGTH - x


@dataclass
class Samples:
    clock: list[int] = field(default_factory=list)
    ball: list[np.ndarray] = field(default_factory=list)
    pos: list[np.ndarray] = field(default_factory=list)


class MatchState:
    def __init__(self, sample_every: int = 5, keep_s: float = 420.0) -> None:
        self.roster = Roster()
        self.sample_every = sample_every
        self.keep_ms = int(keep_s * 1000)
        self.samples: dict[int, Samples] = {1: Samples(), 2: Samples()}
        self.events: dict[str, CleanEvent] = {}
        self.clock_ms: dict[int, int] = {1: -1, 2: -1}
        self.period = 1
        self._timeline: dict[int, tuple[list[int], list[str | None]]] = {}

    def add_frames(self, batch: CleanFrameBatch) -> None:
        s = self.samples[batch.period]
        self.period = max(self.period, batch.period)
        for fr in batch.frames:
            self.clock_ms[batch.period] = max(self.clock_ms[batch.period], fr.match_clock_ms)
            if fr.frame % self.sample_every:
                continue
            if s.clock and fr.match_clock_ms <= s.clock[-1]:
                continue
            arr = np.full((max(len(self.roster.ids), 1) + 8, 2), np.nan)
            for p in fr.players:
                c = self.roster.column(p.player_id)
                if c >= len(arr):
                    arr = np.vstack([arr, np.full((c - len(arr) + 8, 2), np.nan)])
                arr[c] = (p.x, p.y)
            s.clock.append(fr.match_clock_ms)
            s.ball.append(np.array([fr.ball.x, fr.ball.y]))
            s.pos.append(arr)
        cutoff = self.clock_ms[batch.period] - self.keep_ms
        k = bisect_right(s.clock, cutoff)
        if k:
            del s.clock[:k], s.ball[:k], s.pos[:k]

    def upsert(self, ev: CleanEvent) -> bool:
        old = self.events.get(ev.event_id)
        if old is not None and old.version >= ev.version:
            return False
        self.events[ev.event_id] = ev
        self._timeline.pop(ev.period, None)
        return old is None

    def delete(self, ev: CleanEvent) -> None:
        if self.events.pop(ev.event_id, None) is not None:
            self._timeline.pop(ev.period, None)

    def period_events(self, period: int, t0: int, t1: int, types=None) -> list[CleanEvent]:
        out = [e for e in self.events.values() if e.period == period
               and t0 <= e.match_clock_ms <= t1 and e.status == "active"
               and (types is None or e.type in types)]
        return sorted(out, key=lambda e: (e.match_clock_ms, e.event_id))

    def timeline(self, period: int) -> tuple[list[int], list[str | None]]:
        if period not in self._timeline:
            evs = self.period_events(period, -1, 10**9, ON_BALL)
            clocks, teams = [], []
            for e in evs:
                team = e.team_id
                if e.type == "shot" and e.outcome == "goal":
                    team = None
                clocks.append(e.match_clock_ms)
                teams.append(team)
            self._timeline[period] = (clocks, teams)
        return self._timeline[period]

    def possession_at(self, period: int, clocks_ms: np.ndarray) -> np.ndarray:
        tl_clock, tl_team = self.timeline(period)
        idx = np.searchsorted(np.array(tl_clock, dtype=np.int64), clocks_ms, side="right") - 1
        teams = np.array([None] + tl_team, dtype=object)
        return teams[idx + 1]

    def window(self, period: int, t0: int, t1: int) -> dict | None:
        s = self.samples[period]
        if not s.clock:
            return None
        lo, hi = bisect_right(s.clock, t0 - 1), bisect_right(s.clock, t1)
        if hi - lo < 10:
            return None
        n = max(len(p) for p in s.pos[lo:hi])
        pos = np.full((hi - lo, max(n, len(self.roster.ids)), 2), np.nan)
        for i, p in enumerate(s.pos[lo:hi]):
            pos[i, :len(p)] = p
        clocks = np.array(s.clock[lo:hi], dtype=np.int64)
        return {"clock": clocks, "ball": np.array(s.ball[lo:hi]), "pos": pos,
                "poss": self.possession_at(period, clocks)}
