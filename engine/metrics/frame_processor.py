"""Frame processor (LLD §5.1, §5.2, §5.9): name tags, speed, distance, sprints, top speed,
alerts, ball speed, pressure rings, heatmaps. Runs on every frame batch (25 frames per second)."""

import numpy as np

from engine.metrics.calc.pressure import nearest, pressure
from engine.metrics.cues import CueBook
from engine.metrics.memory import DT, MAX_PLAUSIBLE_MS, FrameMemory, Roster
from engine.metrics.models import (
    Evidence,
    MetricDoc,
    MetricsOutput,
    PressureSample,
    StatsMessage,
)
from engine.metrics.totals import TOP_HOLD_FRAMES, Totals
from ingest.clean import CleanFrameBatch

SPRINT_MS = 7.0  # 25.2 km/h
SPRINT_FRAMES = 25  # held ≥ 1 s
FAST_ALERT_MS = 8.9  # 32 km/h
TOP_ALERT_FROM_MS = 600_000  # new match top speed alerts only after 10:00
TOP_ALERT_GAP_MS = 5_000
DISTANCE_MILESTONE_M = 10_000.0
JITTER_MS = 0.1
TOTALS_EVERY_MS = 10_000
CARRIER_M = 1.5
CARRIER_MAX_Z = 1.5


def kmh(ms: float) -> float:
    return round(ms * 3.6, 1)


class FrameProcessor:
    def __init__(self, match_id: str, roster: Roster, memory: FrameMemory, totals: Totals,
                 cues: CueBook) -> None:
        self.match_id = match_id
        self.roster = roster
        self.memory = memory
        self.totals = totals
        self.cues = cues
        self.pressure = np.zeros(len(totals.distance))
        self.match_top = 0.0
        self.last_top_alert_ms = -TOP_ALERT_GAP_MS
        self.totals_bucket: tuple[int, int] | None = None

    def process(self, batch: CleanFrameBatch) -> list[MetricsOutput]:
        out: list[MetricsOutput] = []
        for f in batch.frames:
            if self.memory.append(batch.period, f) < 0:
                continue
            for k in self.memory.smooth_ready():
                out += self._frame(batch.period, k)
        if batch.frames:
            out.append(self._positions(batch))
        return out

    # ---------- per smoothed frame ----------

    def _frame(self, period: int, k: int) -> list[MetricsOutput]:
        m, t = self.memory, self.totals
        s = m.slot(k)
        clock, frame = int(m.clock[s]), int(m.frame[s])
        xy = m.s_pos[s]
        on = ~np.isnan(xy).any(axis=1)
        speed = np.nan_to_num(m.speed[s])
        out: list[MetricsOutput] = []

        # Distance: smoothed displacement per frame, jitter ignored
        if k - 1 >= m.run_start:
            prev = m.slot(k - 1)
            step = np.nan_to_num(np.linalg.norm(xy - m.s_pos[prev], axis=1))
            step[m.seg[prev] != m.seg[s]] = 0.0
            t.distance += np.where((step / DT >= JITTER_MS) & (step / DT <= MAX_PLAUSIBLE_MS),
                                   step, 0.0)

        # Sprints: ≥ 7 m/s held for 1 s
        fast = speed >= SPRINT_MS
        t.run_frames = np.where(fast, t.run_frames + 1, 0)
        t.sprints += t.run_frames == SPRINT_FRAMES
        t.fast_alerted &= fast

        # Top speed: highest speed held for 0.4 s
        t.held[k % TOP_HOLD_FRAMES] = speed
        if k - m.run_start >= TOP_HOLD_FRAMES - 1:
            t.top_speed = np.maximum(t.top_speed, t.held.min(axis=0))

        t.sum_x += np.where(on, np.nan_to_num(xy[:, 0]), 0.0)
        t.sum_y += np.where(on, np.nan_to_num(xy[:, 1]), 0.0)
        t.frames_on += on
        t.add_heat(clock, xy)

        out += self._pressure(period, clock, frame, xy, s)
        out += self._alerts(period, clock, frame, xy, speed)

        bucket = (period, clock // TOTALS_EVERY_MS)
        if self.totals_bucket is None:
            self.totals_bucket = bucket
        elif bucket != self.totals_bucket:
            self.totals_bucket = bucket
            out += self.snapshot(period, clock, frame)
        return out

    def _pressure(self, period, clock, frame, xy, s) -> list[MetricsOutput]:
        """Pressure on every player (rings on screen) and on the ball carrier (to Tactics)."""
        self.pressure[:] = 0.0
        teams = sorted(set(self.roster.teams))
        if len(teams) != 2:
            return []
        cols = {team: self.roster.team_cols(team) for team in teams}
        for team, other in (teams, teams[::-1]):
            d, _ = nearest(xy[cols[team]], xy[cols[other]])
            self.pressure[cols[team]] = np.where(np.isnan(xy[cols[team], 0]), 0.0, pressure(d))

        ball = self.memory.s_ball[s]
        if np.isnan(ball).any() or ball[2] > CARRIER_MAX_Z:
            return []
        d = np.linalg.norm(xy - ball[:2], axis=1)
        if np.isnan(d).all() or np.nanmin(d) > CARRIER_M:
            return []
        c = int(np.nanargmin(d))
        team = self.roster.teams[c]
        opp = cols[teams[1] if team == teams[0] else teams[0]]
        dist, idx = nearest(xy[c], xy[opp])
        live = opp[~np.isnan(xy[opp, 0])]
        presser = self.roster.ids[int(live[idx[0]])] if idx[0] >= 0 else None
        return [PressureSample(
            match_id=self.match_id, period=period, match_clock_ms=clock, frame=frame,
            carrier_id=self.roster.ids[c], team_id=team,
            pressure=round(float(pressure(dist[0])), 3), presser_id=presser)]

    def _alerts(self, period, clock, frame, xy, speed) -> list[MetricsOutput]:
        t, out = self.totals, []
        ids = self.roster.ids
        ev = Evidence(frames=[frame])
        for c in np.flatnonzero((speed >= FAST_ALERT_MS) & ~t.fast_alerted):
            t.fast_alerted[c] = True
            out.append(self.cues.new(
                "speed_alert", period, clock,
                {"player_id": ids[c], "type": "fast", "speed_ms": round(float(speed[c]), 2),
                 "speed_kmh": kmh(float(speed[c]))}, ev, tuple(xy[c])))

        top = float(t.top_speed.max())
        if top > self.match_top + 0.05:
            c = int(np.argmax(t.top_speed))
            if (clock >= TOP_ALERT_FROM_MS and c < len(ids)
                    and clock - self.last_top_alert_ms >= TOP_ALERT_GAP_MS):
                self.last_top_alert_ms = clock
                out.append(self.cues.new(
                    "speed_alert", period, clock,
                    {"player_id": ids[c], "type": "match_top_speed", "speed_ms": round(top, 2),
                     "speed_kmh": kmh(top)}, ev, tuple(xy[c])))
            self.match_top = top

        for c in np.flatnonzero((t.distance >= DISTANCE_MILESTONE_M) & ~t.milestone_done):
            t.milestone_done[c] = True
            if c < len(ids) and not np.isnan(xy[c]).any():
                out.append(self.cues.new(
                    "distance_milestone", period, clock,
                    {"player_id": ids[c], "distance_m": round(float(t.distance[c]))},
                    ev, tuple(xy[c])))
        return out

    # ---------- outputs ----------

    def _positions(self, batch: CleanFrameBatch) -> StatsMessage:
        """Raw positions for the pitch plus the latest smoothed tag values (PM-1, 2, 6)."""
        m, t = self.memory, self.totals
        tags, ball_speed = {}, None
        if m.smoothed_to >= 0:
            s = m.slot(m.smoothed_to)
            ball_speed = None if np.isnan(m.ball_speed[s]) else round(float(m.ball_speed[s]), 2)
            for c, pid in enumerate(self.roster.ids):
                if np.isnan(m.s_pos[s, c]).any():
                    continue
                sp = float(np.nan_to_num(m.speed[s, c]))
                tags[pid] = {"speed_ms": round(sp, 2), "speed_kmh": kmh(sp),
                             "distance_m": round(float(t.distance[c]), 1),
                             "pressure": round(float(self.pressure[c]), 2)}
        last = batch.frames[-1]
        return StatsMessage(
            kind="positions", match_id=self.match_id, period=batch.period,
            match_clock_ms=last.match_clock_ms,
            values={
                "frames": [{"frame": f.frame, "match_clock_ms": f.match_clock_ms,
                            "interpolated": f.interpolated,
                            "ball": [round(f.ball.x, 2), round(f.ball.y, 2), round(f.ball.z, 2)],
                            "players": {p.player_id: [round(p.x, 2), round(p.y, 2)]
                                        for p in f.players}}
                           for f in batch.frames],
                "tags": tags, "ball_speed_ms": ball_speed},
            evidence=Evidence(frames=[f.frame for f in batch.frames]))

    def player_totals(self, c: int) -> dict:
        t = self.totals
        n = int(t.frames_on[c])
        return {
            "distance_m": round(float(t.distance[c]), 1),
            "sprints": int(t.sprints[c]),
            "top_speed_ms": round(float(t.top_speed[c]), 2),
            "passes": int(t.passes[c]),
            "passes_completed": int(t.passes_completed[c]),
            "pass_accuracy": round(t.passes_completed[c] / t.passes[c], 3) if t.passes[c] else None,
            "completion_vs_expected": round(float(t.passes_completed[c] - t.expected_completed[c]),
                                            2),
            "shots": int(t.shots[c]), "xg": round(float(t.xg[c]), 3),
            # Sums, so the Stats API gets any from…to average by subtraction
            "sum_x": round(float(t.sum_x[c]), 1), "sum_y": round(float(t.sum_y[c]), 1),
            "frames_on": n,
            "avg_position": [round(float(t.sum_x[c]) / n, 1), round(float(t.sum_y[c]) / n, 1)]
            if n else None,
        }

    def snapshot(self, period: int, clock: int, frame: int) -> list[MetricsOutput]:
        """Every 10 s: totals for the screen and Cosmos, and heatmaps (PM-24, PM-29)."""
        out: list[MetricsOutput] = []
        players = {pid: self.player_totals(c) for c, pid in enumerate(self.roster.ids)}
        teams = sorted(set(self.roster.teams))
        out.append(StatsMessage(kind="player_totals", match_id=self.match_id, period=period,
                                match_clock_ms=clock, values={"players": players},
                                evidence=Evidence(frames=[frame])))
        for pid, body in players.items():
            out.append(MetricDoc(id=f"player:{pid}:{clock}", match_id=self.match_id,
                                 type="player_totals", period=period, match_clock_ms=clock,
                                 body={"player_id": pid, **body}))
        whole, recent = self.totals.heat, self.totals.recent_heat()
        for team in teams:
            maps = {}
            for c in self.roster.team_cols(team):
                maps[self.roster.ids[c]] = {"match": _shares(whole[c]),
                                            "last_15": _shares(recent[c])}
            out.append(StatsMessage(kind="heatmap", match_id=self.match_id, period=period,
                                    match_clock_ms=clock, team_id=team,
                                    values={"grid": [whole.shape[1], whole.shape[2]],
                                            "players": maps},
                                    evidence=Evidence(frames=[frame])))
        return out


def _shares(counts: np.ndarray) -> list[list[float]] | None:
    total = counts.sum()
    if not total:
        return None
    return np.round(counts / total, 3).tolist()
