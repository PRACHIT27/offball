"""Event processor (LLD §5.4–5.8): pass quality, shots, open options, decision score, decoy runs,
xG range. Runs on each pass and shot, reading the frames around it from memory.

Each result is kept in a ledger with what it added to the running totals and the frame-derived
inputs it used, so the correction handler can undo it and recompute after the frames are gone.
"""

from dataclasses import dataclass, field

import numpy as np

from engine.metrics.calc.decoy import decoy_runs
from engine.metrics.calc.pass_model import decision_score, difficulty, lane_opponents, options
from engine.metrics.calc.pass_model import p_complete as pass_p_complete
from engine.metrics.calc.pitch_value import attack_x, pitch_value
from engine.metrics.calc.pressure import nearest, pressure
from engine.metrics.calc.xg_range import BIG_CHANCE_XG, chance_story
from engine.metrics.cues import CueBook
from engine.metrics.memory import FrameMemory, Roster, team_of
from engine.metrics.models import Evidence, MetricDoc, MetricsOutput, PassValues, StatsMessage
from engine.metrics.totals import Totals
from ingest.clean import CleanEvent

PEAK_WINDOW_MS = 300  # pass and shot speed: peak ball speed in the 0.3 s after
DECOY_WINDOW_MS = 3_000
MAX_WAIT_MS = 10_000  # give up waiting for frames after this much match time
BEST_OPTION_BELOW = 0.4  # ghost arrow when the choice scored under this and the best was open
HANDLED = ("pass", "shot")


@dataclass
class Snapshot:
    """Frame-derived inputs for one event, kept for corrections (frames last only 10 s)."""

    frame: int | None = None
    positions: dict[str, list[float]] = field(default_factory=dict)
    peak_speed_ms: float | None = None
    decoy_receiver: str | None = None
    decoys: list[dict] = field(default_factory=list)

    def to_state(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Entry:
    """One event's current result: what it added to the totals, and its inputs."""

    event: CleanEvent
    snapshot: Snapshot
    added: dict[str, dict[str, float]]  # player_id → {totals field: amount}


class EventProcessor:
    def __init__(self, match_id: str, roster: Roster, memory: FrameMemory, totals: Totals,
                 cues: CueBook) -> None:
        self.match_id = match_id
        self.roster = roster
        self.memory = memory
        self.totals = totals
        self.cues = cues
        self.ledger: dict[str, Entry] = {}
        self.pending: list[CleanEvent] = []
        # team → {event_id: provider xG}
        self.team_xg: dict[str, dict[str, float]] = {}

    # ---------- waiting for frames ----------

    def frames_ready(self, ev: CleanEvent) -> bool:
        m = self.memory
        if m.period != ev.period:
            return m.period is not None and m.period > ev.period
        latest = m.latest_smoothed_clock()
        raw = m.latest_clock()
        return (latest is not None and latest >= ev.match_clock_ms + PEAK_WINDOW_MS) or (
            raw is not None and raw - ev.match_clock_ms >= MAX_WAIT_MS)

    def submit(self, ev: CleanEvent) -> list[MetricsOutput]:
        """New pass or shot: compute now if its frames are in, else wait for them."""
        if self.frames_ready(ev):
            return self.apply(ev, self.snapshot(ev))
        self.pending = [p for p in self.pending if p.event_id != ev.event_id] + [ev]
        return []

    def release_ready(self) -> list[MetricsOutput]:
        out: list[MetricsOutput] = []
        ready = [ev for ev in self.pending if self.frames_ready(ev)]
        self.pending = [ev for ev in self.pending if ev not in ready]
        for ev in ready:
            out += self.apply(ev, self.snapshot(ev))
        return out

    # ---------- snapshot from memory ----------

    def snapshot(self, ev: CleanEvent) -> Snapshot:
        m, snap = self.memory, Snapshot()
        s = m.nearest_index(ev.period, ev.match_clock_ms)
        if s is not None:
            snap.frame = int(m.frame[s])
            for c, pid in enumerate(self.roster.ids):
                if not np.isnan(m.pos[s, c]).any():
                    snap.positions[pid] = [round(float(v), 2) for v in m.pos[s, c]]
        w = m.window(ev.period, ev.match_clock_ms, ev.match_clock_ms + PEAK_WINDOW_MS)
        if w is not None and not np.isnan(w.ball_speed).all():
            snap.peak_speed_ms = round(float(np.nanmax(w.ball_speed)), 2)
        if ev.type == "pass" and ev.outcome == "complete" and ev.target_player_id:
            snap.decoy_receiver = ev.target_player_id
            snap.decoys = self._decoys(ev)
        return snap

    def _decoys(self, ev: CleanEvent) -> list[dict]:
        w = self.memory.window(ev.period, ev.match_clock_ms - DECOY_WINDOW_MS, ev.match_clock_ms)
        if w is None:
            return []
        n = len(self.roster.ids)
        pos, speed = w.smooth_pos[:, :n], w.speed[:, :n]
        rows = ~np.isnan(pos).all(axis=(1, 2))
        runs = decoy_runs(pos[rows], speed[rows], self.roster.ids, self.roster.teams,
                          ev.player_id, ev.target_player_id)
        return [r.__dict__ for r in runs]

    # ---------- results ----------

    def apply(self, ev: CleanEvent, snap: Snapshot) -> list[MetricsOutput]:
        """Replace any earlier result for this event with one computed from `ev` and `snap`."""
        prev = self.ledger.get(ev.event_id)
        if prev and prev.event.version > ev.version:
            return []
        self._undo(prev)
        if ev.status == "deleted" or ev.type not in HANDLED or not ev.player_id:
            self.ledger.pop(ev.event_id, None)
            return self._removed(ev, prev)
        if ev.type == "pass":
            values, added, extra = self._pass(ev, snap)
        else:
            values, added, extra = self._shot(ev, snap)
        self._add(added)
        self.ledger[ev.event_id] = Entry(ev, snap, added)
        evidence = Evidence(event_ids=[ev.event_id],
                            frames=[snap.frame] if snap.frame is not None else [])
        out: list[MetricsOutput] = [
            StatsMessage(kind=ev.type, match_id=self.match_id, period=ev.period,
                         match_clock_ms=ev.match_clock_ms, player_id=ev.player_id,
                         team_id=ev.team_id, version=ev.version, values=values,
                         best_option=extra.get("best_option"), evidence=evidence),
            MetricDoc(id=f"event:{ev.event_id}:{ev.version}", match_id=self.match_id,
                      type="event_result", period=ev.period, match_clock_ms=ev.match_clock_ms,
                      body={"event_id": ev.event_id, "version": ev.version, "type": ev.type,
                            "status": "active", "player_id": ev.player_id,
                            "team_id": ev.team_id, **values,
                            "best_option": extra.get("best_option")}),
        ]
        if "pass_values" in extra:
            out.append(extra["pass_values"])
        out += self._cues(ev, prev, extra["cues"], evidence)
        if ev.type == "shot" or (prev and prev.event.type == "shot"):
            out += self._xg_update(ev)
        return out

    def _pass(self, ev: CleanEvent, snap: Snapshot):
        home = self.roster.home_id
        team = ev.team_id
        goal_x = attack_x(team, home) if home else 105.0
        pos = snap.positions
        start = _xy(ev.start) or pos.get(ev.player_id)
        end = _xy(ev.end) or pos.get(ev.target_player_id or "")
        opps = np.array([p for pid, p in pos.items() if team_of(pid) != team]).reshape(-1, 2)
        mates = {pid: tuple(p) for pid, p in pos.items()
                 if team_of(pid) == team and pid != ev.player_id}
        p_passer = _pressure_at(pos.get(ev.player_id) or start, opps)
        p_receiver = _pressure_at(pos.get(ev.target_player_id or "") or end, opps)
        distance = float(np.hypot(end[0] - start[0], end[1] - start[1])) if start and end else None
        lane = lane_opponents(start, end, opps) if start and end else 0
        pc = pass_p_complete(distance or 0.0, lane, p_passer, p_receiver)
        completed = ev.outcome == "complete"

        opts = options(start, mates, opps, goal_x, p_passer) if start and mates else []
        score, best = decision_score(ev.target_player_id, opts)
        decoys = snap.decoys if completed and snap.decoy_receiver == ev.target_player_id else []
        v_start = float(pitch_value(*start, goal_x)) if start else 0.0
        v_end = float(pitch_value(*end, goal_x)) if end else 0.0

        values = {
            "receiver_id": ev.target_player_id, "completed": completed,
            "distance_m": round(distance, 1) if distance is not None else None,
            "speed_ms": snap.peak_speed_ms, "difficulty": difficulty(pc),
            "p_complete": round(pc, 3), "lane_opponents": lane,
            "pressure_passer": round(p_passer, 2), "pressure_receiver": round(p_receiver, 2),
            "open_options": sum(o.open for o in opts) if opts else None,
            "decision_score": score,
            "decoy_credit": {d["runner_id"]: len(d["pulled"]) for d in decoys},
            "value_gain": round(v_end - v_start, 3),
        }
        best_option = ({"player_id": best.player_id, "x": round(best.x, 2), "y": round(best.y, 2),
                        "value": round(best.value, 3), "open": best.open} if best else None)
        added = {ev.player_id: {"passes": 1, "passes_completed": int(completed),
                                "expected_completed": pc}}

        cues: dict[str, tuple] = {}
        if start and end:
            cues["pass_arc"] = ("pass_arc", {
                "passer_id": ev.player_id, "receiver_id": ev.target_player_id,
                "start": [start[0], start[1]], "end": [end[0], end[1]],
                "completed": completed, "distance_m": values["distance_m"],
                "speed_ms": snap.peak_speed_ms, "difficulty": values["difficulty"]}, start)
        if score is not None and score < BEST_OPTION_BELOW and best and best.open \
                and best.player_id != ev.target_player_id:
            cues["best_option"] = ("best_option", {
                "passer_id": ev.player_id, "chosen_id": ev.target_player_id,
                "best": best_option, "decision_score": score}, start)
        for d in decoys:
            cues[f"decoy_run:{d['runner_id']}"] = ("decoy_run", {
                "runner_id": d["runner_id"], "credit": len(d["pulled"]), "pulled": d["pulled"],
                "path": d["path"], "defenders": d["defenders"],
                "receiver_id": ev.target_player_id}, d["path"][-1])
        pass_values = PassValues(
            match_id=self.match_id, period=ev.period, match_clock_ms=ev.match_clock_ms,
            event_id=ev.event_id, version=ev.version, team_id=team, passer_id=ev.player_id,
            receiver_id=ev.target_player_id, completed=completed, p_complete=round(pc, 3),
            value_start=round(v_start, 3), value_end=round(v_end, 3),
            value_gain=round(v_end - v_start, 3))
        return values, added, {"best_option": best_option, "cues": cues,
                               "pass_values": pass_values}

    def _shot(self, ev: CleanEvent, snap: Snapshot):
        xg = ev.provider_xg
        values = {"outcome": ev.outcome, "speed_ms": snap.peak_speed_ms,
                  "speed_kmh": round(snap.peak_speed_ms * 3.6, 1) if snap.peak_speed_ms else None,
                  "xg": xg, "big_chance": xg is not None and xg >= BIG_CHANCE_XG}
        added = {ev.player_id: {"shots": 1, "xg": xg or 0.0}}
        self.team_xg.setdefault(ev.team_id, {})[ev.event_id] = xg or 0.0
        cues = {}
        start = _xy(ev.start) or snap.positions.get(ev.player_id)
        if snap.peak_speed_ms is not None:
            cues["shot_speed"] = ("shot_speed", {
                "player_id": ev.player_id, "speed_ms": snap.peak_speed_ms,
                "speed_kmh": values["speed_kmh"], "xg": xg, "outcome": ev.outcome}, start)
        return values, added, {"cues": cues}

    # ---------- totals ----------

    def _add(self, added: dict[str, dict[str, float]], sign: int = 1) -> None:
        for pid, fields in added.items():
            c = self.roster.column(pid)
            if c is None:
                continue
            for name, amount in fields.items():
                getattr(self.totals, name)[c] += sign * amount

    def _undo(self, prev: Entry | None) -> None:
        if prev is None:
            return
        self._add(prev.added, -1)
        if prev.event.type == "shot":
            self.team_xg.get(prev.event.team_id, {}).pop(prev.event.event_id, None)

    # ---------- cues and removals ----------

    def _cues(self, ev: CleanEvent, prev: Entry | None, wanted: dict[str, tuple],
              evidence: Evidence) -> list[MetricsOutput]:
        # LLD §4: a pass corrected from complete to not complete loses its cues
        if prev and prev.event.type == "pass" and prev.event.outcome == "complete" \
                and ev.outcome != "complete":
            wanted = {}
        out: list[MetricsOutput] = []
        keys = {f"{ev.event_id}:{k}": v for k, v in wanted.items()}
        for key in self.cues.keys_for_event(ev.event_id):
            if key not in keys:
                cue = self.cues.withdraw(key)
                out += [cue] if cue else []
        for key, (kind, data, anchor) in keys.items():
            cue = self.cues.upsert(key, kind, ev.period, ev.match_clock_ms, data, evidence,
                                   anchor)
            out += [cue] if cue else []
        return out

    def _removed(self, ev: CleanEvent, prev: Entry | None) -> list[MetricsOutput]:
        """The event was deleted or is no longer a pass or shot: withdraw what it produced."""
        if prev is None:
            return []
        out: list[MetricsOutput] = []
        for key in self.cues.keys_for_event(ev.event_id):
            cue = self.cues.withdraw(key)
            out += [cue] if cue else []
        old = prev.event
        evidence = Evidence(event_ids=[ev.event_id])
        out.append(StatsMessage(kind=old.type, match_id=self.match_id, period=old.period,
                                match_clock_ms=old.match_clock_ms, player_id=old.player_id,
                                team_id=old.team_id, version=ev.version, status="deleted",
                                values={}, evidence=evidence))
        out.append(MetricDoc(id=f"event:{ev.event_id}:{ev.version}", match_id=self.match_id,
                             type="event_result", period=old.period,
                             match_clock_ms=old.match_clock_ms,
                             body={"event_id": ev.event_id, "version": ev.version,
                                   "type": old.type, "status": "deleted",
                                   "player_id": old.player_id, "team_id": old.team_id}))
        if old.type == "pass":
            out.append(PassValues(
                match_id=self.match_id, period=old.period, match_clock_ms=old.match_clock_ms,
                event_id=ev.event_id, version=ev.version, status="deleted", team_id=old.team_id,
                passer_id=old.player_id, receiver_id=old.target_player_id, completed=False,
                p_complete=0.0, value_start=0.0, value_end=0.0, value_gain=0.0))
        if old.type == "shot":
            out += self._xg_update(old)
        return out

    def _xg_update(self, ev: CleanEvent) -> list[MetricsOutput]:
        """Team xG range and chance story after any shot change (PM-14, PM-15)."""
        team = ev.team_id
        shots = self.team_xg.get(team, {})
        key = f"xg:{team}"
        evidence = Evidence(event_ids=sorted(shots))
        if not shots:
            cue = self.cues.withdraw(key)
            return [cue] if cue else []
        story = chance_story(list(shots.values()))
        out: list[MetricsOutput] = [StatsMessage(
            kind="xg", match_id=self.match_id, period=ev.period, match_clock_ms=ev.match_clock_ms,
            team_id=team, values=story, evidence=evidence)]
        cue = self.cues.upsert(key, "xg_summary", ev.period, ev.match_clock_ms,
                               {"team_id": team, **story}, evidence)
        return out + ([cue] if cue else [])

    def to_state(self) -> dict:
        return {"ledger": {k: {"event": e.event.model_dump(mode="json"),
                               "snapshot": e.snapshot.to_state(), "added": e.added}
                           for k, e in self.ledger.items()},
                "pending": [ev.model_dump(mode="json") for ev in self.pending],
                "team_xg": self.team_xg}

    def load_state(self, state: dict) -> None:
        self.ledger = {k: Entry(CleanEvent.model_validate(e["event"]), Snapshot(**e["snapshot"]),
                                e["added"]) for k, e in state["ledger"].items()}
        self.pending = [CleanEvent.model_validate(ev) for ev in state["pending"]]
        self.team_xg = state["team_xg"]


def _xy(p) -> tuple[float, float] | None:
    return (p.x, p.y) if p is not None else None


def _pressure_at(point, opps: np.ndarray) -> float:
    if point is None or not len(opps):
        return 0.0
    return float(pressure(nearest([point], opps)[0][0]))
