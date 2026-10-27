from dataclasses import dataclass, field

import numpy as np

from engine.tactics.config import TacticsConfig

TEAM_MEASURES = ("line_height_m", "pressing_per_min", "style_dial", "formation_out")


@dataclass
class Snapshot:
    window_id: str
    team: str
    period: int
    play_ms: int
    clock_ms: int
    values: dict
    positions: dict


@dataclass
class Hold:
    since_play: int
    since_clock: int
    period: int
    before: object
    after: object
    earlier_id: str
    tentative: bool = False
    confirmed: bool = False
    misses: int = 0


@dataclass
class ChangeDetector:
    cfg: TacticsConfig
    history: dict[str, list[Snapshot]] = field(default_factory=dict)
    holds: dict[tuple, Hold] = field(default_factory=dict)
    baseline: dict[str, dict] = field(default_factory=dict)
    next_note: int = 1

    def earlier(self, snap: Snapshot) -> Snapshot | None:
        target = snap.play_ms - int(self.cfg.compare_gap_s * 1000)
        cands = [s for s in self.history.get(snap.team, []) if s.play_ms <= target]
        return cands[-1] if cands else None

    def update_baseline(self, snap: Snapshot) -> None:
        lo, hi = self.cfg.baseline_from_min * 60000, self.cfg.baseline_to_min * 60000
        if snap.period != 1 or not lo <= snap.clock_ms <= hi:
            return
        b = self.baseline.setdefault(snap.team, {"n": 0, "sums": {}})
        b["n"] += 1
        for k in ("line_height_m", "pressing_per_min", "style_dial"):
            v = snap.values.get(k)
            if v is not None:
                b["sums"].setdefault(k, []).append(v)

    def normal(self, team: str) -> dict:
        b = self.baseline.get(team)
        if not b or b["n"] < 6:
            return {}
        out = {}
        for k, vals in b["sums"].items():
            m = float(np.mean(vals))
            tol = {"line_height_m": max(4.0, 0.15 * m), "pressing_per_min": max(0.5, 0.3 * m),
                   "style_dial": 15.0}[k]
            out[k] = (round(m - tol, 2), round(m + tol, 2))
        return out

    def unusual(self, snap: Snapshot) -> list[str]:
        out = []
        for k, (lo, hi) in self.normal(snap.team).items():
            v = snap.values.get(k)
            if v is not None and not lo <= v <= hi:
                out.append(k)
        return out

    def changed(self, key: str, before, after) -> bool:
        if before is None or after is None:
            return False
        if key == "line_height_m":
            return abs(after - before) >= self.cfg.line_height_m
        if key == "pressing_per_min":
            return abs(after - before) >= self.cfg.pressing_min_abs and \
                abs(after - before) / max(before, 0.1) * 100 >= self.cfg.pressing_pct
        if key == "style_dial":
            return abs(after - before) >= self.cfg.style_points
        if key == "formation_out":
            return before != after
        return np.hypot(after[0] - before[0], after[1] - before[1]) >= self.cfg.player_position_m

    def observe(self, snap: Snapshot) -> list[dict]:
        self.update_baseline(snap)
        prev_list = self.history.setdefault(snap.team, [])
        last = prev_list[-1] if prev_list else None
        prev_list.append(snap)
        if len(prev_list) > 400:
            del prev_list[:100]
        old = self.earlier(snap)
        if old is None:
            return []
        pairs = []
        for k in TEAM_MEASURES:
            after = snap.values.get(k)
            if k == "formation_out" and (last is None or last.values.get(k) != after):
                after = None
            pairs.append(((snap.team, k), k, old.values.get(k), after, None))
        for pid, pos in snap.positions.items():
            if "out" in pos and pid in old.positions and "out" in old.positions[pid]:
                pairs.append(((snap.team, "player", pid), "player", old.positions[pid]["out"],
                              pos["out"], pid))
        notes = []
        for key, measure, before, after, pid in pairs:
            anchored = self.holds.get(key)
            if anchored is not None:
                if anchored.confirmed and self.changed(measure, anchored.after, after):
                    before = anchored.after
                    del self.holds[key]
                else:
                    before = anchored.before
            if self.changed(measure, before, after):
                h = self.holds.get(key)
                if h is None:
                    h = self.holds[key] = Hold(snap.play_ms, snap.clock_ms, snap.period, before,
                                              after, old.window_id)
                if not h.confirmed:
                    h.after = after
                h.misses = 0
                held = (snap.play_ms - h.since_play) / 1000
                for level, need, flag in (("tentative", self.cfg.tentative_s, "tentative"),
                                          ("confirmed", self.cfg.confirmed_s, "confirmed")):
                    if held >= need and not getattr(h, flag):
                        setattr(h, flag, True)
                        notes.append(self.note(snap, measure, pid, h, level))
            elif key in self.holds:
                h = self.holds[key]
                h.misses += 1
                if h.misses >= 2:
                    del self.holds[key]
        return notes

    def note(self, snap: Snapshot, measure: str, pid, h: Hold, level: str) -> dict:
        nid = f"n-{self.next_note:04d}"
        self.next_note += 1
        change = "player_position" if measure == "player" else measure
        return {"kind": "note", "note_id": nid, "team_id": snap.team, "level": level,
                "change": change, "player_id": pid, "before": h.before, "after": h.after,
                "since_ms": h.since_clock, "since_period": h.period, "at_ms": snap.clock_ms,
                "period": snap.period, "play_ms": snap.play_ms,
                "window_ids": [h.earlier_id, snap.window_id],
                "unusual": measure in self.unusual(snap)}


class Promoter:
    def __init__(self, cfg: TacticsConfig):
        self.cfg = cfg
        self.player_notes: dict[str, list[int]] = {}
        self.last_crux: dict[str, int] = {}

    def crux(self, team: str | None, play_ms: int) -> None:
        for t in ([team] if team else list(self.last_crux) or []):
            self.last_crux[t] = play_ms

    def promote(self, note: dict) -> str | None:
        if note["level"] != "confirmed":
            return None
        team, t = note["team_id"], note["play_ms"]
        crux_at = self.last_crux.get(team)
        if crux_at is not None and t - crux_at <= self.cfg.after_crux_s * 1000:
            return "after_crux"
        if note["change"] == "player_position":
            times = [x for x in self.player_notes.get(team, [])
                     if t - x <= self.cfg.reshuffle_window_s * 1000] + [t]
            self.player_notes[team] = times
            if len(times) >= self.cfg.reshuffle_players:
                self.player_notes[team] = []
                return "reshuffle"
            return "unusual" if note.get("unusual") else None
        return "team_change"
