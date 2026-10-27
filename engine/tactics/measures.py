import warnings

import numpy as np

from engine.tactics.state import LENGTH, WIDTH, MatchState, depth

DEF_ACTIONS = {"tackle", "interception", "foul"}
GRID = (21, 14)


def pitch_value(x: float, y: float, team: str, state: MatchState) -> float:
    d = float(depth(state.roster, team, x))
    goal = np.array([LENGTH, 34.0])
    here = np.array([d, y])
    dist = float(np.linalg.norm(goal - here))
    a = np.arctan2(34 + 3.66 - y, max(LENGTH - d, 0.01))
    b = np.arctan2(34 - 3.66 - y, max(LENGTH - d, 0.01))
    angle = abs(a - b)
    return float(np.clip(np.exp(-dist / 18) * (0.4 + 0.6 * angle / 1.2), 0, 1))


def _nanmedian(a) -> float | None:
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    return float(np.median(a)) if len(a) else None


def _round(v, nd=2):
    return None if v is None else round(float(v), nd)


def lines_formation(depths: np.ndarray) -> str | None:
    d = np.sort(depths[~np.isnan(depths)])
    if len(d) < 6:
        return None
    gaps = np.diff(d)
    cuts = np.sort(np.argsort(gaps[1:-1])[-2:] + 1)
    sizes = np.diff(np.concatenate([[0], cuts + 1, [len(d)]]))
    return "-".join(str(int(s)) for s in sizes)


class WindowCalc:
    min_opp_minutes = 1.0
    min_passes = 25

    def __init__(self, state: MatchState, team: str, period: int, t0: int, t1: int, win: dict):
        self.s, self.team, self.period, self.t0, self.t1, self.w = state, team, period, t0, t1, win
        r = state.roster
        self.opp = r.other(team)
        self.cols = r.cols(team)
        self.opp_cols = r.cols(self.opp)
        pos = win["pos"]
        self.x = pos[:, self.cols, 0]
        self.y = pos[:, self.cols, 1]
        self.dep = depth(r, team, self.x)
        self.bdep = depth(r, team, win["ball"][:, 0])
        self.poss = win["poss"]
        self.oop = self.poss == self.opp
        self.inp = self.poss == team
        self.events = state.period_events(period, t0, t1)
        self.minutes = max((t1 - t0) / 60000, 1e-6)

    def line_height(self) -> tuple[float | None, np.ndarray]:
        d = self.dep[self.oop]
        if not len(d):
            return None, np.array([])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            srt = np.sort(d, axis=1)
            per = np.nanmean(srt[:, :4], axis=1)
        return _nanmedian(per), per

    def compactness(self) -> tuple[float | None, float | None]:
        d, y = self.dep[self.oop], self.y[self.oop]
        if not len(d):
            return None, None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            length = np.nanmax(d, axis=1) - np.nanmin(d, axis=1)
            width = np.nanpercentile(y, 90, axis=1) - np.nanpercentile(y, 10, axis=1)
        return _nanmedian(length), _nanmedian(width)

    def formations(self) -> tuple[str | None, str | None]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            out = (lines_formation(np.nanmean(self.dep[self.oop], axis=0))
                   if self.oop.any() else None)
            inn = (lines_formation(np.nanmean(self.dep[self.inp], axis=0))
                   if self.inp.any() else None)
        return out, inn

    def pressing(self) -> dict:
        ball = self.w["ball"]
        dist = np.linalg.norm(self.w["pos"][:, self.cols, :] - ball[:, None, :], axis=2)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            nearest = np.nanmin(dist, axis=1)
        zone = self.bdep >= 42
        pressing = self.oop & zone & (nearest <= 2.0)
        onsets, last = [], -10**12
        for i in np.flatnonzero(pressing & ~np.concatenate([[False], pressing[:-1]])):
            if self.w["clock"][i] - last >= 2000:
                onsets.append(i)
                last = self.w["clock"][i]
        opp_minutes = float(np.sum(self.oop)) * 0.2 / 60
        sizes = [int(np.sum(dist[i] <= 8.0)) for i in onsets]
        triggers: dict[str, int] = {}
        gk = self.s.roster.gk(self.opp)
        opp_passes = [e for e in self.events if e.type == "pass" and e.team_id == self.opp]
        for i in onsets:
            t = int(self.w["clock"][i])
            prior = [e for e in opp_passes if t - 3000 <= e.match_clock_ms <= t]
            kind = "other"
            if prior:
                e = prior[-1]
                if e.target_player_id and e.target_player_id == gk:
                    kind = "pass_to_keeper"
                elif e.start and e.end and depth(self.s.roster, self.opp, e.end.x) \
                        < depth(self.s.roster, self.opp, e.start.x) - 3:
                    kind = "back_pass"
                elif e.end and (e.end.y < 14 or e.end.y > WIDTH - 14):
                    kind = "pass_wide"
            triggers[kind] = triggers.get(kind, 0) + 1
        opp_pass_zone = sum(1 for e in opp_passes if self.in_attack_zone(e))
        actions = sum(1 for e in self.events if e.team_id == self.team and e.type in DEF_ACTIONS
                      and self.in_attack_zone(e))
        enough = opp_minutes >= self.min_opp_minutes
        return {"pressing_per_min": round(len(onsets) / opp_minutes, 2) if enough else None,
                "press_size": _round(np.mean(sizes) if sizes else None, 1),
                "press_triggers": triggers,
                "ppda": _round(opp_pass_zone / actions if actions else None, 1)}

    def in_attack_zone(self, e) -> bool:
        return e.start is not None and depth(self.s.roster, self.team, e.start.x) >= 42

    def possessions(self) -> list[tuple[str | None, int, int, list]]:
        seq, cur = [], None
        for e in self.events:
            if e.type not in ("pass", "take_on", "tackle", "interception", "clearance", "shot"):
                continue
            if cur is None or cur[0] != e.team_id:
                if cur:
                    seq.append(cur)
                cur = [e.team_id, e.match_clock_ms, e.match_clock_ms, [e]]
            else:
                cur[2] = e.match_clock_ms
                cur[3].append(e)
        if cur:
            seq.append(cur)
        return [tuple(c) for c in seq]

    def style(self, seqs) -> dict:
        passes = [e for e in self.events if e.type == "pass" and e.team_id == self.team
                  and e.start and e.end]
        if len(passes) < self.min_passes:
            return {"style_dial": None, "avg_pass_length_m": None, "long_ball_share": None}
        lengths = np.array([np.hypot(e.end.x - e.start.x, e.end.y - e.start.y) for e in passes])
        mine = [s for s in seqs if s[0] == self.team]
        speeds, per = [], []
        for _, a, b, evs in mine:
            per.append(sum(1 for e in evs if e.type == "pass"))
            starts = [e for e in evs if e.start]
            if len(starts) >= 2 and b > a:
                gain = depth(self.s.roster, self.team, starts[-1].start.x) \
                    - depth(self.s.roster, self.team, starts[0].start.x)
                speeds.append(max(gain, 0) / ((b - a) / 1000))
        parts = [np.clip((lengths.mean() - 10) / 25, 0, 1), float(np.mean(lengths > 30)),
                 np.clip((np.mean(speeds) if speeds else 0) / 3, 0, 1),
                 1 - np.clip(((np.mean(per) if per else 1) - 1) / 9, 0, 1)]
        return {"style_dial": round(100 * float(np.mean(parts)), 1),
                "avg_pass_length_m": round(float(lengths.mean()), 1),
                "long_ball_share": round(float(np.mean(lengths > 30)), 2)}

    def chaos(self, seqs, line_series: np.ndarray) -> dict:
        changes = max(len(seqs) - 1, 0)
        lengths = [(b - a) / 1000 for _, a, b, _ in seqs if b > a]
        ball = self.w["ball"]
        speed = np.linalg.norm(np.diff(ball, axis=0), axis=1) / 0.2 if len(ball) > 1 else [0]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            centroid = np.nanmean(self.dep, axis=1)
        inst = float(np.nanstd(line_series)) if len(line_series) else 0.0
        inst += float(np.nanstd(centroid)) if len(centroid) else 0.0
        parts = [np.clip(changes / self.minutes / 3, 0, 1),
                 1 - np.clip(((np.mean(lengths) if lengths else 2) - 2) / 18, 0, 1),
                 np.clip(inst / 16, 0, 1), np.clip(float(np.std(speed)) / 10, 0, 1)]
        known = np.array([p is not None for p in self.poss], dtype=bool)
        share = float(np.mean(self.inp[known])) if known.any() else None
        return {"chaos": round(100 * float(np.mean(parts)), 1), "control_share": _round(share),
                "tempo_epm": round(len(self.events) / self.minutes, 1)}

    def offside_traps(self) -> int:
        clocks = self.w["clock"]
        traps = 0
        for e in self.events:
            if e.type != "pass" or e.team_id != self.opp or not (e.start and e.end):
                continue
            r = self.s.roster
            if depth(r, self.opp, e.end.x) - depth(r, self.opp, e.start.x) < 5:
                continue
            i1 = int(np.searchsorted(clocks, e.match_clock_ms))
            i0 = int(np.searchsorted(clocks, e.match_clock_ms - 1000))
            if i1 >= len(clocks) or i0 >= i1:
                continue
            back = np.argsort(np.nan_to_num(self.dep[i0], nan=999))[:4]
            moved = self.dep[i1, back] - self.dep[i0, back]
            if np.sum(moved >= 2.0) >= 3:
                traps += 1
        return traps

    def recovery(self, seqs) -> float | None:
        times = []
        for i, (team, _, b, _) in enumerate(seqs):
            if team != self.team:
                continue
            nxt = next((s for s in seqs[i + 1:] if s[0] == self.team), None)
            if nxt and i + 1 < len(seqs) and seqs[i + 1][0] == self.opp:
                times.append((nxt[1] - b) / 1000)
        return _round(np.median(times) if times else None, 1)

    def network(self) -> dict:
        r = self.s.roster
        edges: dict[tuple[str, str], list[float]] = {}
        for e in self.events:
            if e.type == "pass" and e.team_id == self.team and e.outcome == "complete" \
                    and e.player_id and e.target_player_id and e.start and e.end:
                gain = pitch_value(e.end.x, e.end.y, self.team, self.s) \
                    - pitch_value(e.start.x, e.start.y, self.team, self.s)
                edges.setdefault((e.player_id, e.target_player_id), []).append(max(gain, 0))
        nodes = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            if self.inp.any():
                avg = np.nanmean(self.w["pos"][self.inp], axis=0)
                for p in {a for k in edges for a in k}:
                    c = r.col.get(p)
                    if c is not None and c < len(avg) and not np.isnan(avg[c, 0]):
                        nodes[p] = [round(float(avg[c, 0]), 1), round(float(avg[c, 1]), 1)]
        return {"nodes": nodes,
                "edges": [{"from": a, "to": b, "passes": len(v), "danger": round(sum(v), 3)}
                          for (a, b), v in sorted(edges.items(), key=lambda kv: -len(kv[1]))]}

    def routes(self, seqs) -> dict:
        lanes = {"left": 0, "centre": 0, "right": 0}
        players: dict[str, int] = {}
        r = self.s.roster
        for team, _, _, evs in seqs:
            if team != self.team or not any(e.type == "shot" for e in evs):
                continue
            entry = next((e for e in evs if e.start and depth(r, team, e.start.x) > 70), None)
            spot = entry.start if entry else next((e.start for e in evs if e.start), None)
            if spot is None:
                continue
            y = spot.y if team == r.home else WIDTH - spot.y
            lanes["left" if y > 2 * WIDTH / 3 else "right" if y < WIDTH / 3 else "centre"] += 1
            for e in evs:
                if e.player_id:
                    players[e.player_id] = players.get(e.player_id, 0) + 1
        total = sum(lanes.values())
        return {"chances": total,
                "lanes": {k: round(v / total, 2) if total else 0.0 for k, v in lanes.items()},
                "players": dict(sorted(players.items(), key=lambda kv: -kv[1])[:5])}

    def positions(self) -> dict:
        r = self.s.roster
        out = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            a_in = np.nanmean(self.w["pos"][self.inp], axis=0) if self.inp.any() else None
            a_out = np.nanmean(self.w["pos"][self.oop], axis=0) if self.oop.any() else None
        for c in r.cols(self.team, outfield=False):
            pid = r.ids[c]
            item = {}
            for key, avg in (("in", a_in), ("out", a_out)):
                if avg is not None and c < len(avg) and not np.isnan(avg[c, 0]):
                    item[key] = [round(float(avg[c, 0]), 1), round(float(avg[c, 1]), 1)]
            if item:
                out[pid] = item
        return out

    def territory(self) -> dict:
        res = {}
        for key, mask in (("in", self.inp), ("out", self.oop)):
            pts = self.w["pos"][mask][:, self.cols, :].reshape(-1, 2)
            pts = pts[~np.isnan(pts[:, 0])]
            h, _, _ = np.histogram2d(pts[:, 0], pts[:, 1], bins=GRID,
                                     range=[[0, LENGTH], [0, WIDTH]]) if len(pts) else \
                (np.zeros(GRID), None, None)
            total = h.sum()
            res[key] = np.round(h / total, 4).tolist() if total else np.zeros(GRID).tolist()
        return res

    def compute(self, with_territory: bool = False) -> dict:
        seqs = self.possessions()
        line, line_series = self.line_height()
        length, width = self.compactness()
        f_out, f_in = self.formations()
        values = {"line_height_m": _round(line, 1), "length_m": _round(length, 1),
                  "width_m": _round(width, 1), "formation_out": f_out, "formation_in": f_in,
                  "offside_traps": self.offside_traps(), "recovery_s": self.recovery(seqs)}
        values.update(self.pressing())
        values.update(self.style(seqs))
        values.update(self.chaos(seqs, line_series))
        out = {"values": values, "network": self.network(), "routes": self.routes(seqs),
               "positions": self.positions()}
        if with_territory:
            out["territory"] = self.territory()
        return out
