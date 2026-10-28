from dataclasses import dataclass, field

import numpy as np

from ingest.clean import FRAME_MS, PERIOD_BASE_MS
from sim.clubs import CLUBS, SQUAD, STARTING_SHIRTS, Club, prematch
from sim.storyline import Storyline
from sim.tactics import FORMATIONS, TEN_MAN, TacticProfile, assign_slots

DT = FRAME_MS / 1000
CENTRE = np.array([52.5, 34.0])
SPRINT_MS = 7.0
FOUL_REASONS = ["late_tackle", "from_behind", "holding", "pushing"]
SHAPE_MIN_LENGTH = 18.0
ONSIDE_JOG_MS = 5.0
DROP_GOAL_SIDE_M = 10.0
SHOT_BIAS = 0.8
GK_ADVANCE, GK_MAX_M = 0.18, 20.0
PASS_WEIGHTS = {"open": 1.2, "open_m": 10.0, "progress": 1.0, "fit": 0.6, "lane": 0.8,
                "lane_m": 2.0, "return": 1.2, "gk": 1.2}
START_HINT = {1: (0, .1), 2: (0, .37), 3: (0, .63), 4: (0, .9), 5: (.4, .5), 6: (.5, .3),
              7: (.5, .7), 8: (1, .15), 9: (1, .5), 10: (1, .85)}


@dataclass
class PeriodFrames:
    ball: np.ndarray
    pos: np.ndarray
    codes: np.ndarray
    possession: np.ndarray | None = None


@dataclass
class Truth:
    match_id: str
    storyline: str
    seed: int
    home: str
    away: str
    players: list[str]
    prematch: dict
    events: list[dict] = field(default_factory=list)
    frames: dict[int, PeriodFrames] = field(default_factory=dict)
    tactic_changes: list[dict] = field(default_factory=list)
    true_player_stats: dict = field(default_factory=dict)
    score: dict = field(default_factory=dict)

    def period_length_ms(self, period: int) -> int:
        return len(self.frames[period].ball) * FRAME_MS


def sigmoid(x: float) -> float:
    return float(1 / (1 + np.exp(-x)))


def seg_dist(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((points - a) @ ab) / max(float(ab @ ab), 1e-9), 0, 1)
    return np.linalg.norm(points - (a + np.outer(t, ab)), axis=1)


class Engine:
    def __init__(self, story: Storyline):
        self.story = story
        self.rng = np.random.default_rng(story.seed)
        self.clubs: dict[str, Club] = {story.home: CLUBS[story.home], story.away: CLUBS[story.away]}
        self.home, self.away = story.home, story.away
        self.players = [p["player_id"] for c in (self.home, self.away)
                        for p in self.clubs[c].players]
        self.code = {p: i for i, p in enumerate(self.players)}
        self.profile = {p["player_id"]: p for c in self.clubs.values() for p in c.players}
        self.truth = Truth(story.match_id, story.name, story.seed, self.home, self.away,
                           self.players, prematch(story.match_id, self.clubs[self.home],
                                                  self.clubs[self.away], story.start_conditions))
        self.slot_code = np.array([self.code[f"{self.team_of(s)}-{STARTING_SHIRTS[s % 11]:02d}"]
                                   for s in range(22)])
        self.on = np.ones(22, dtype=bool)
        self.abil = np.zeros((22, 11))
        for s in range(22):
            self._load_abilities(s)
        self.stamina = np.ones(22)
        self.tactics = {t: self.clubs[t].manager.identity for t in (self.home, self.away)}
        self.slot_idx = {t: {} for t in (self.home, self.away)}
        for t in (self.home, self.away):
            self.slot_idx[t] = assign_slots(
                {s: START_HINT[s % 11] for s in self.outfield(t)}, self.tactics[t].formation)
        self.next_event = 1
        self.yellows: dict[str, int] = {}
        self.score = {self.home: 0, self.away: 0}
        self.pending: list[tuple[int, int, str, dict, dict]] = []
        self.late_checked: set[tuple[str, str]] = set()
        self.force_goal = {self.home: -1, self.away: -1}
        self.cond = dict(story.start_conditions)
        scripted = any(dv.action == "goal" for dv in story.directives)
        self.natural_goals = 0.0 if scripted else 0.3
        self.natural_reds = not scripted and not any(dv.action == "red_card"
                                                     for dv in story.directives)
        self.dist = np.zeros(len(self.players))
        self.top = np.zeros(len(self.players))
        self.sprints = np.zeros(len(self.players), dtype=int)
        self.sprint_run = np.zeros(22)
        self.last_tackle = -100

    ABIL = ["pace", "acceleration", "passing", "vision", "finishing", "dribbling", "tackling",
            "discipline", "goalkeeping", "stamina", "positioning"]

    def _load_abilities(self, s: int) -> None:
        a = self.profile[self.players[self.slot_code[s]]]["abilities"]
        self.abil[s] = [a.get(k, 50) for k in self.ABIL]

    def a(self, s: int, key: str) -> float:
        return float(self.abil[s, self.ABIL.index(key)])

    def team_of(self, slot: int) -> str:
        return self.home if slot < 11 else self.away

    def other(self, team: str) -> str:
        return self.away if team == self.home else self.home

    def d(self, team: str) -> float:
        return 1.0 if team == self.home else -1.0

    def x0(self, team: str) -> float:
        return 0.0 if team == self.home else 105.0

    def depth(self, team: str, x):
        return (np.asarray(x) - self.x0(team)) * self.d(team)

    def goal(self, team: str) -> np.ndarray:
        return np.array([105.0 if team == self.home else 0.0, 34.0])

    def gk(self, team: str) -> int:
        return 0 if team == self.home else 11

    def on_team(self, team: str) -> np.ndarray:
        idx = np.arange(11) if team == self.home else np.arange(11, 22)
        return idx[self.on[idx]]

    def outfield(self, team: str) -> list[int]:
        return [int(s) for s in self.on_team(team) if s != self.gk(team)]

    def nearest(self, team: str, point, exclude=()) -> int:
        cands = [s for s in self.on_team(team) if s not in exclude]
        dd = np.linalg.norm(self.pos[cands] - point, axis=1)
        return int(cands[int(np.argmin(dd))])

    def wait(self, lo: float, hi: float) -> int:
        return int(self.rng.uniform(lo, hi) / DT)

    def clock_ms(self, f: int) -> int:
        return PERIOD_BASE_MS[self.period] + f * FRAME_MS

    def minute(self, f: int) -> float:
        return self.clock_ms(f) / 60000

    @staticmethod
    def xy(p) -> dict:
        return {"x": round(float(p[0]), 2), "y": round(float(p[1]), 2)}

    def emit(self, f: int, type_: str, slot: int | None = None, **kw) -> dict:
        ev = {
            "event_id": f"e-{self.next_event:06d}", "version": 1, "status": "active",
            "match_id": self.story.match_id, "match_clock_ms": self.clock_ms(f),
            "period": self.period, "type": type_,
            "team_id": self.team_of(slot) if slot is not None else kw.pop("team_id", None),
            "player_id": self.players[self.slot_code[slot]] if slot is not None else None,
            "target_player_id": None, "start": None, "end": None, "outcome": None,
            "qualifiers": [], "provider_xg": None, "details": None,
        }
        ev.update(kw)
        self.next_event += 1
        self.truth.events.append(ev)
        return ev

    def change_tactics(self, team: str, new: TacticProfile, cause: dict, f: int) -> None:
        old = self.tactics[team]
        n_out = len(self.outfield(team))
        if len(FORMATIONS[new.formation]) != n_out:
            new = new.adjusted(formation=TEN_MAN.get(new.formation, "4-4-1"))
        if new == old:
            return
        before, after = old.diff(new)
        self.tactics[team] = new
        current = {s: FORMATIONS[old.formation][self.slot_idx[team][s]]
                   for s in self.outfield(team) if s in self.slot_idx[team]}
        for s in self.outfield(team):
            current.setdefault(s, (0.5, 0.5))
        self.slot_idx[team] = assign_slots(current, new.formation)
        self.truth.tactic_changes.append({
            "at_clock_ms": self.clock_ms(f), "period": self.period, "team_id": team,
            "cause": cause, "before": before, "after": after})

    def schedule_reaction(self, team: str, rule: str, f: int, trigger_event: str | None) -> None:
        style = self.clubs[team].manager.reaction_style.get(rule)
        if not style:
            return
        risk = self.clubs[team].manager.risk_appetite
        scale = 0.75 + 0.5 * risk
        delta = {}
        for k, v in style.items():
            if k in ("delay_s", "from_minute"):
                continue
            delta[k] = int(round(v * scale)) if k == "pressers" else v * scale
        if rule == "on_red_card":
            delta["formation"] = TEN_MAN.get(self.tactics[team].formation, "4-4-1")
        due = f + int(style.get("delay_s", 30) / DT)
        self.pending.append((self.period, due, team, delta,
                             {"type": "reaction", "rule": rule, "trigger_event_id": trigger_event}))

    def check_late(self, f: int) -> None:
        minute = self.minute(f)
        for team in (self.home, self.away):
            diff = self.score[team] - self.score[self.other(team)]
            for rule, cond in (("on_lead_late", diff > 0), ("on_trailing_late", diff < 0)):
                style = self.clubs[team].manager.reaction_style.get(rule)
                if not style or not cond or (team, rule) in self.late_checked:
                    continue
                if rule == "on_trailing_late" and len(self.outfield(team)) < 10:
                    continue
                if minute >= style["from_minute"]:
                    self.late_checked.add((team, rule))
                    self.schedule_reaction(team, rule, f, None)

    def apply_pending(self, f: int) -> None:
        keep = []
        for item in self.pending:
            period, due, team, delta, cause = item
            if period == self.period and f >= due:
                if cause["rule"] == "on_trailing_late" and len(self.outfield(team)) < 10:
                    continue
                new = self.tactics[team].adjusted(**delta)
                self.change_tactics(team, new, cause, f)
            else:
                keep.append(item)
        self.pending = keep

    def kick(self, f: int, to, speed: float, then, arc: float = 0.0):
        start = self.ball[:2].copy()
        dist = float(np.linalg.norm(np.asarray(to) - start))
        n = max(int(dist / speed / DT), 6)
        self.flight = {"from": start, "to": np.asarray(to, dtype=float), "f0": f, "f1": f + n,
                       "arc": arc, "then": then}
        self.carrier = None

    def give(self, slot: int, f: int, lo=None, hi=None):
        team = self.team_of(slot)
        tempo = self.tactics[team].tempo_s
        lo = tempo * 1.3 if lo is None else lo
        hi = tempo * 2.8 if hi is None else hi
        self.pos[slot] = self.ball[:2] - [self.d(team) * 0.4, 0]
        self.vel[slot] *= 0.3
        self.carrier = slot
        self.last_from = None
        self.possession = team
        self.next_action = f + self.wait(lo, hi)

    def pressure_on(self, slot: int) -> tuple[float, int]:
        opp = self.on_team(self.other(self.team_of(slot)))
        dd = np.linalg.norm(self.pos[opp] - self.pos[slot], axis=1)
        k = int(np.argmin(dd))
        return float(np.clip((5 - dd[k]) / 4, 0, 1)), int(opp[k])

    def true_xg(self, team: str, at: np.ndarray) -> float:
        g = self.goal(team)
        dist = float(np.linalg.norm(g - at))
        angle = abs(np.arctan2(at[1] - 34, abs(g[0] - at[0]) + 1e-6))
        opp = self.on_team(self.other(team))
        cone = seg_dist(self.pos[opp], at, g)
        blockers = int(np.sum((cone < 1.5) & (np.linalg.norm(self.pos[opp] - g, axis=1) < dist)))
        return sigmoid(0.6 - 0.16 * dist - 1.2 * angle - 0.5 * blockers)

    def act(self, f: int):
        c = self.carrier
        team = self.team_of(c)
        tac = self.tactics[team]
        here = self.pos[c]
        opp = self.on_team(self.other(team))
        pressure, _ = self.pressure_on(c)
        if self.kickoff_hold:
            self.kickoff_hold = False
            return self.act_pass(f, c, team, choose_short=True)
        mates = [s for s in self.on_team(team) if s != c]
        rel = self.pos[mates] - here
        dist = np.linalg.norm(rel, axis=1)
        near_opp = np.array([np.min(np.linalg.norm(self.pos[opp] - self.pos[m], axis=1))
                             for m in mates])
        pw = PASS_WEIGHTS
        openness = np.clip(near_opp / pw["open_m"], 0, 1)
        progress = np.clip(rel[:, 0] * self.d(team) / 30, -1, 1)
        norm_len = np.clip((dist - 5) / 35, 0, 1)
        fit = 1 - np.abs(norm_len - tac.pass_length_pref)
        lane = np.array([int(np.sum(seg_dist(self.pos[opp], here, self.pos[m]) < pw["lane_m"]))
                         for m in mates])
        forcing = self.force_goal[team] >= 0
        scores = (pw["open"] * openness + (1.6 if forcing else pw["progress"]) * progress
                  + pw["fit"] * fit - pw["lane"] * lane)
        scores[(dist < 4) | (dist > 50)] = -9
        scores[[m == self.gk(team) for m in mates]] -= pw["gk"]
        scores[[m == self.last_from for m in mates]] -= pw["return"] * (1 - pressure)
        options = [("pass", m) for m in mates]
        all_scores = list(scores)
        gd = float(np.linalg.norm(self.goal(team) - here))
        if gd < (34 if forcing else 28):
            options.append(("shot", None))
            all_scores.append(3.0 * self.true_xg(team, here) - SHOT_BIAS
                              + (2.6 if forcing else 0.0))
        ahead = [o for o in opp if (self.pos[o][0] - here[0]) * self.d(team) > 0]
        space = min([float(np.linalg.norm(self.pos[o] - here)) for o in ahead] or [10]) / 10
        options.append(("carry", None))
        all_scores.append(0.5 * min(space, 1) - 0.6 * pressure + (0.4 if forcing else 0))
        if self.depth(team, here[0]) < 30 and pressure > 0.5:
            options.append(("clearance", None))
            all_scores.append(0.6 * pressure)
        temp = 0.6 - 0.4 * self.a(c, "vision") / 100
        w = np.exp((np.array(all_scores) - max(all_scores)) / temp)
        kind, target = options[int(self.rng.choice(len(options), p=w / w.sum()))]
        if kind == "pass":
            self.act_pass(f, c, team, receiver=target, pressure=pressure,
                          lane=int(lane[mates.index(target)]))
        elif kind == "shot":
            self.act_shot(f, c, team)
        elif kind == "carry":
            self.next_action = f + self.wait(1.0, 2.2)
        else:
            self.act_clearance(f, c, team)

    def act_pass(self, f, c, team, receiver=None, pressure=0.0, lane=0, choose_short=False):
        if receiver is None:
            mates = [s for s in self.outfield(team) if s != c]
            dd = np.linalg.norm(self.pos[mates] - self.pos[c], axis=1)
            receiver = mates[int(np.argsort(dd)[1 if choose_short and len(dd) > 1 else 0])]
        r = receiver
        length = float(np.linalg.norm(self.pos[r] - self.pos[c]))
        rp, _ = self.pressure_on(r)
        p = sigmoid(3.4 - 0.05 * length - 0.9 * lane - 0.8 * pressure - 0.6 * rp
                    + 1.5 * (self.a(c, "passing") / 100 - 0.5)
                    - (0.15 if self.cond.get("weather") == "heavy_rain" else 0.0))
        success = self.rng.random() < p
        end = self.pos[r] + self.vel[r] * min(length / 15, 1.5) + self.rng.normal(0, 0.6, 2)
        if not success:
            end = end + self.rng.normal(0, 3.5, 2)
        end = np.clip(end, [1, 1], [104, 67])
        long_ball = length > 30
        self.emit(f, "pass", c, target_player_id=self.players[self.slot_code[r]],
                  start=self.xy(self.ball), end=self.xy(end),
                  outcome="complete" if success else "incomplete",
                  qualifiers=["long_ball"] if long_ball else [])

        def land(f_end):
            if success:
                self.give(r, f_end)
                self.last_from = c
            elif self.rng.random() < 0.45:
                i = self.nearest(self.other(team), end)
                spot = np.array([end[0], 0.5 if end[1] < 34 else 67.5])
                self.restart(f_end, self.wait(8, 14), slot=i, spot=spot)
            else:
                i = self.nearest(self.other(team), end)
                self.emit(f_end, "interception", i, start=self.xy(end), outcome="success")
                self.give(i, f_end)

        self.receiver, self.receiver_to = r, end
        speed = float(np.clip(12 + 0.25 * length, 12, 25))
        self.kick(f, end, speed, land, arc=min(6.0, length / 6) if long_ball else 0.0)

    def act_shot(self, f, c, team):
        here = self.pos[c].copy()
        xg = self.true_xg(team, here)
        opp = self.other(team)
        p_goal = xg * (0.8 + 0.4 * self.a(c, "finishing") / 100) \
            * (1.1 - 0.3 * self.a(self.gk(opp), "goalkeeping") / 100)
        if self.force_goal[team] >= 0:
            outcome = "goal"
        elif self.rng.random() < p_goal * self.natural_goals:
            outcome = "goal"
        else:
            outcome = str(self.rng.choice(["saved", "off_target", "post"], p=[0.45, 0.47, 0.08]))
        if outcome == "goal":
            self.force_goal[team] = -1
        g = self.goal(team)
        dy = {"goal": self.rng.uniform(-3, 3), "saved": self.rng.uniform(-3, 3),
              "post": self.rng.choice([-3.66, 3.66]),
              "off_target": self.rng.choice([-1, 1]) * self.rng.uniform(5, 10)}[outcome]
        to = g + [0, dy]
        provider = float(np.clip(xg * 1.1 * (1 + self.rng.normal(0, 0.15)), 0.01, 0.95))
        ev = self.emit(f, "shot", c, start=self.xy(here), end=self.xy(to), outcome=outcome,
                       provider_xg=round(provider, 3))
        speed = float(np.clip(20 + 13 * self.a(c, "finishing") / 100 - 0.1
                              * np.linalg.norm(g - here), 18, 33))

        def land(f_end):
            if outcome == "goal":
                self.score[team] += 1
                self.check_late(f_end)
                self.restart(f_end, self.wait(18, 22), kickoff_team=opp)
                self.last_goal_event = ev["event_id"]
            elif outcome == "saved":
                self.give(self.gk(opp), f_end, 2, 4)
            else:
                spot = np.array([5.5 if opp == self.home else 99.5, 34.0])
                self.restart(f_end, self.wait(5, 7), slot=self.gk(opp), spot=spot)

        self.kick(f, to, speed, land)

    def act_clearance(self, f, c, team):
        to = np.clip(self.ball[:2] + [self.d(team) * self.rng.uniform(35, 50),
                                      self.rng.uniform(-15, 15)], [2, 2], [103, 66])
        self.emit(f, "clearance", c, start=self.xy(self.ball), end=self.xy(to), outcome="success")

        def land(f_end):
            both = list(self.on_team(self.home)) + list(self.on_team(self.away))
            dd = np.linalg.norm(self.pos[both] - to, axis=1)
            self.give(both[int(np.argmin(dd))], f_end)

        self.kick(f, to, 18.0, land, arc=8.0)

    def challenge(self, f: int):
        c = self.carrier
        team = self.team_of(c)
        _, defender = self.pressure_on(c)
        if np.linalg.norm(self.pos[defender] - self.pos[c]) > 1.3 or f - self.last_tackle < 25:
            return
        if self.rng.random() > 0.22:
            return
        self.last_tackle = f
        behind = (self.pos[defender][0] - self.pos[c][0]) * self.d(team) < 0
        p_foul = 0.12 + 0.15 * (1 - self.a(defender, "discipline") / 100) + (0.1 if behind else 0)
        if self.rng.random() < p_foul:
            reasons = ["from_behind"] if behind else [str(self.rng.choice(FOUL_REASONS))]
            self.emit(f, "foul", defender, start=self.xy(self.pos[c]), qualifiers=reasons)
            self.discipline(f + 1, defender, behind)
            if self.carrier is not None or self.on[c]:
                self.restart(f + 1, self.wait(7, 9), slot=c, spot=self.ball[:2].copy())
            return
        p_win = sigmoid(0.5 * (self.a(defender, "tackling") - self.a(c, "dribbling")) / 20 - 0.3)
        if self.rng.random() < p_win:
            self.emit(f, "tackle", defender, start=self.xy(self.ball), outcome="success")
            self.give(defender, f)
        else:
            self.emit(f, "take_on", c, start=self.xy(self.ball), outcome="success")
            self.next_action = f + self.wait(0.5, 1.2)

    def discipline(self, f: int, slot: int, behind: bool):
        pid = self.players[self.slot_code[slot]]
        disc = self.a(slot, "discipline")
        if self.natural_reds and self.rng.random() < 0.01:
            self.send_off(f, slot, ["serious_foul_play"])
        elif self.rng.random() < 0.10 + 0.15 * (1 - disc / 100):
            if self.yellows.get(pid, 0) and not self.natural_reds:
                return
            self.yellows[pid] = self.yellows.get(pid, 0) + 1
            if self.yellows[pid] >= 2 and self.natural_reds:
                self.send_off(f, slot, ["second_yellow"])
            else:
                self.emit(f, "card", slot, outcome="yellow",
                          qualifiers=["reckless_challenge" if behind else "tactical_foul"])

    def send_off(self, f: int, slot: int, reasons: list[str]):
        if not self.on[slot] or slot == self.gk(self.team_of(slot)):
            return
        team = self.team_of(slot)
        ev = self.emit(f, "card", slot, outcome="red", qualifiers=reasons)
        self.on[slot] = False
        self.slot_idx[team].pop(slot, None)
        if self.carrier == slot:
            self.carrier = None
        self.schedule_reaction(team, "on_red_card", f, ev["event_id"])

    def restart(self, f, wait, kickoff_team=None, slot=None, spot=None):
        self.carrier, self.flight = None, None
        self.dead_until = f + wait
        self.after_dead = ("kickoff", kickoff_team) if kickoff_team else ("spot", slot, spot)

    def kickoff(self, f, team):
        cands = self.outfield(team)
        taker = max(cands, key=lambda s: FORMATIONS[self.tactics[team].formation]
                    [self.slot_idx[team].get(s, 0)][0])
        self.pos[taker] = CENTRE - [self.d(team) * 0.6, 0]
        self.ball[:] = [*CENTRE, 0.0]
        self.carrier = taker
        self.possession = team
        self.kickoff_hold = True
        self.next_action = f + 3

    def directives(self, f: int):
        for i, dv in enumerate(self.story.directives):
            if i in self.done or dv.period != self.period or f < int(dv.at_s / DT):
                continue
            if dv.action == "set_tactics":
                new = self.tactics[dv.team].adjusted(**dv.tactics)
                self.change_tactics(dv.team, new, {"type": "storyline", "rule": "set_tactics",
                                                   "trigger_event_id": None}, f)
            elif dv.action == "conditions":
                self.cond.update(dv.conditions)
                self.emit(f, "conditions", None, details=dict(self.cond))
            elif dv.action == "goal":
                self.force_goal[dv.team] = f
            elif self.flight is not None or self.dead_until > f:
                continue
            elif dv.action == "stoppage":
                self.stoppage_n = getattr(self, "stoppage_n", 0) + 1
                sid = f"s{self.stoppage_n}"
                self.emit(f, "stoppage_start", None,
                          details={"stoppage_id": sid, "reason": dv.conditions["reason"]})
                end = f + int(dv.conditions["seconds"] / DT)
                self.stoppage_end = (end, sid, dv.conditions["reason"])
                self.restart(f, end - f, slot=self.carrier, spot=self.ball[:2].copy())
            elif dv.action == "sub":
                found = np.flatnonzero(self.slot_code == self.code[dv.player])
                if len(found) == 0 or not self.on[found[0]]:
                    self.done.add(i)
                    continue
                slot = int(found[0])
                if slot == self.carrier:
                    continue
                self.emit(f, "sub_off", slot)
                self.slot_code[slot] = self.code[dv.sub_on]
                self._load_abilities(slot)
                self.stamina[slot] = 1.0
                self.emit(f, "sub_on", slot)
            elif dv.action == "red_card":
                found = np.flatnonzero(self.slot_code == self.code[dv.player])
                if len(found) == 0 or not self.on[found[0]]:
                    self.done.add(i)
                    continue
                slot = int(found[0])
                if slot == self.carrier:
                    continue
                self.send_off(f, slot, ["denying_goal_chance"])
            self.done.add(i)
        if getattr(self, "stoppage_end", None) and self.stoppage_end[0] == f:
            _, sid, reason = self.stoppage_end
            self.emit(f, "stoppage_end", None, details={"stoppage_id": sid, "reason": reason})
            self.stoppage_end = None
        for team in (self.home, self.away):
            started = self.force_goal[team]
            if started >= 0 and f - started > int(90 / DT) and self.carrier is not None \
                    and self.team_of(self.carrier) == team and self.flight is None \
                    and (self.depth(team, self.pos[self.carrier][0]) > 52
                         or self.n_frames - f < int(60 / DT)):
                self.act_shot(f, self.carrier, team)

    def targets(self, f: int) -> np.ndarray:
        tgt = self.pos.copy()
        self.urgent = np.zeros(22, dtype=bool)
        self.hurry = np.zeros(22, dtype=bool)
        bx, by = self.ball[0], self.ball[1]
        carrier_team = self.team_of(self.carrier) if self.carrier is not None else None
        for team in (self.home, self.away):
            tac = self.tactics[team]
            d, x0 = self.d(team), self.x0(team)
            bd = float(self.depth(team, bx))
            outs = self.outfield(team)
            if not outs:
                continue
            slots = np.array([FORMATIONS[tac.formation][self.slot_idx[team].get(s, 0)]
                              for s in outs])
            in_poss = self.possession == team
            if in_poss:
                back = float(np.clip(tac.line_height_m + 8 + 0.35 * (bd - 52.5), 15, 62))
                length, width = tac.length_m * 1.45, min(tac.width_m * 1.2, 64)
            else:
                back = tac.line_height_m + 0.25 * (bd - 52.5)
                back = float(np.clip(back, tac.line_height_m - 6, tac.line_height_m + 8))
                if tac.offside_trap and carrier_team == self.other(team) and bd > 35 \
                        and self.next_action - f < 10:
                    back += 3.0
                back = max(tac.line_height_m - 7, min(back, bd - 1.5))
                back = max(6.0, min(back, bd - DROP_GOAL_SIDE_M))
                length, width = tac.length_m, tac.width_m
            last_line = None
            if in_poss:
                opp = self.outfield(self.other(team))
                if opp:
                    opp_depth = np.sort(self.depth(team, self.pos[opp, 0]))[::-1]
                    last_line = max(float(opp_depth[0]), bd)
                    top = max(float(slots[:, 0].max()), 0.5)
                    length = min(length, max(SHAPE_MIN_LENGTH, (last_line - 0.5 - back) / top))
            dep = np.clip(back + slots[:, 0] * length, 3, 101)
            if last_line is not None:
                fwd = slots[:, 0] >= 0.9
                dep[fwd] = np.minimum(dep[fwd], last_line - 0.5)
                now = self.depth(team, self.pos[outs, 0])
                self.hurry[np.asarray(outs)[now > last_line - 0.5]] = True
            ys = np.clip(34 + (slots[:, 1] - 0.5) * width + 0.35 * (by - 34), 2, 66)
            tgt[outs, 0] = x0 + d * dep
            tgt[outs, 1] = ys
            g = self.gk(team)
            tgt[g] = [x0 + d * float(np.clip(3 + GK_ADVANCE * bd, 2, GK_MAX_M)),
                      34 + 0.3 * (by - 34)]
            if not in_poss and self.carrier is not None and carrier_team == self.other(team):
                cpos = self.pos[self.carrier]
                dd = np.linalg.norm(self.pos[outs] - cpos, axis=1)
                order = np.argsort(dd)
                n_press = 0
                for k in order:
                    s = outs[k]
                    if n_press < tac.pressers and dd[k] < tac.press_distance_m:
                        tgt[s] = cpos - d * np.array([0.8, 0])
                        self.urgent[s] = True
                        n_press += 1
                    elif n_press == 0 and dd[k] < 6:
                        tgt[s] = cpos - d * np.array([3.0, 0])
                        self.urgent[s] = True
                        n_press += 1
                    else:
                        break
        if self.carrier is not None and not self.kickoff_hold:
            c = self.carrier
            ct = self.team_of(c)
            tgt[c] = self.pos[c] + [self.d(ct) * 4, 0.3 * (34 - self.pos[c][1]) / 10]
            self.urgent[c] = True
        if self.flight is not None and self.receiver is not None:
            tgt[self.receiver] = self.receiver_to
            self.urgent[self.receiver] = True
        if self.kickoff_hold and self.carrier is not None:
            tgt[self.carrier] = self.pos[self.carrier]
        return tgt

    def move(self, f: int):
        tgt = self.targets(f)
        delta = tgt - self.pos
        dist = np.linalg.norm(delta, axis=1, keepdims=True)
        pace, acc, stam = self.abil[:, 0:1], self.abil[:, 1:2], self.abil[:, 9]
        vmax = (5.5 + 4.0 * pace / 100) * (0.85 + 0.15 * self.stamina[:, None])
        if self.cond.get("pitch") in ("wet", "heavy"):
            vmax *= 0.97
        cruise = np.where(self.urgent, vmax[:, 0],
                          np.where(dist[:, 0] > 15, 6.5, np.where(dist[:, 0] > 6, 3.4, 2.0)))
        cruise = np.where(self.hurry & ~self.urgent, np.maximum(cruise, ONSIDE_JOG_MS), cruise)
        reach = np.where(self.urgent, 0.35, 1.5)[:, None]
        desired = np.where(dist > 1e-6, delta / np.maximum(dist, 1e-6), 0) \
            * np.minimum(cruise[:, None], dist / reach)
        amax = (2.5 + 2.5 * acc / 100) * DT
        dv = desired - self.vel
        mag = np.linalg.norm(dv, axis=1, keepdims=True)
        dv = np.where(mag > amax, dv / np.maximum(mag, 1e-9) * amax, dv)
        self.vel = self.vel + dv
        self.vel[~self.on] = 0
        self.pos = np.clip(self.pos + self.vel * DT, [0.5, 0.5], [104.5, 67.5])
        speed = np.linalg.norm(self.vel, axis=1)
        hot = 1.2 if self.cond.get("temperature_c", 14) > 28 else 1.0
        drain = 0.00002 * np.maximum(0, speed - 4.0) ** 2 * (1.3 - 0.6 * stam / 100) * hot
        recover = np.where(speed < 2.0, 0.000004, 0)
        self.stamina = np.clip(self.stamina - drain + recover, 0.3, 1.0)
        on = np.flatnonzero(self.on)
        codes = self.slot_code[on]
        np.add.at(self.dist, codes, speed[on] * DT)
        self.top[codes] = np.maximum(self.top[codes], speed[on])
        fast = speed >= SPRINT_MS
        self.sprint_run = np.where(fast & self.on, self.sprint_run + DT, 0)
        started = np.flatnonzero((np.abs(self.sprint_run - 1.0) < DT / 2) & self.on)
        np.add.at(self.sprints, self.slot_code[started], 1)

    def run_period(self, period: int, length_s: float, kickoff_team: str) -> PeriodFrames:
        self.period = period
        n = int(length_s / DT)
        self.n_frames = n
        self.pos = np.zeros((22, 2))
        self.vel = np.zeros((22, 2))
        self.ball = np.array([*CENTRE, 0.0])
        self.possession = kickoff_team
        self.carrier, self.flight, self.receiver = None, None, None
        self.last_from = None
        self.dead_until, self.after_dead, self.kickoff_hold = -1, None, False
        self.next_action = 0
        self.done, self.stoppage_end = set(), None
        self.pos = self.targets(0)
        for t in (self.home, self.away):
            own_half = self.depth(t, self.pos[self.on_team(t), 0])
            self.pos[self.on_team(t), 0] = self.x0(t) + self.d(t) * np.minimum(own_half, 50)
        balls = np.zeros((n, 3))
        poss = np.full((n, 22, 2), np.nan)
        codes = np.full((n, 22), -1, dtype=np.int16)
        possession = np.full(n, -1, dtype=np.int8)
        self.emit(0, "period_start", None)
        if period == 1:
            self.emit(0, "conditions", None, details=dict(self.cond))
        self.kickoff(0, kickoff_team)
        for f in range(n):
            if f == n - 1:
                self.emit(f, "period_end", None)
            self.directives(f)
            self.apply_pending(f)
            if f % 250 == 0:
                self.check_late(f)
            if self.dead_until == f:
                kind = self.after_dead
                if kind[0] == "kickoff":
                    self.kickoff(f, kind[1])
                else:
                    _, slot, spot = kind
                    if slot is None or not self.on[slot]:
                        slot = self.gk(self.possession)
                    self.ball[:] = [*spot, 0.0]
                    self.give(slot, f)
            elif self.flight is not None:
                fl = self.flight
                s = (f - fl["f0"]) / (fl["f1"] - fl["f0"])
                self.ball[:2] = fl["from"] + (fl["to"] - fl["from"]) * s
                self.ball[2] = fl["arc"] * 4 * s * (1 - s)
                if f >= fl["f1"]:
                    self.flight, self.receiver = None, None
                    self.ball[2] = 0.0
                    fl["then"](f)
            elif self.carrier is not None and self.dead_until < f:
                pressed, _ = self.pressure_on(self.carrier)
                if f >= self.next_action or (pressed > 0.85 and not self.kickoff_hold
                                             and self.rng.random() < 0.15):
                    self.act(f)
                elif not self.kickoff_hold:
                    self.challenge(f)
                    if self.carrier is not None and self.flight is None:
                        c = self.carrier
                        self.ball[:2] = self.pos[c] + [self.d(self.team_of(c)) * 0.4, 0]
            self.move(f)
            balls[f] = self.ball
            poss[f, self.on] = self.pos[self.on]
            codes[f, self.on] = self.slot_code[self.on]
            if self.dead_until < f:
                possession[f] = 0 if self.possession == self.home else 1
        return PeriodFrames(balls, poss, codes, possession)


def simulate(story: Storyline, period_s=(2790.0, 2880.0)) -> Truth:
    eng = Engine(story)
    for period, length in zip((1, 2), period_s, strict=True):
        eng.truth.frames[period] = eng.run_period(
            period, length, eng.home if period == 1 else eng.away)
    eng.truth.score = dict(eng.score)
    eng.truth.true_player_stats = {
        p: {"distance_m": round(float(eng.dist[i]), 1),
            "top_speed_ms": round(float(eng.top[i]), 2),
            "sprints": int(eng.sprints[i])}
        for i, p in enumerate(eng.players) if eng.dist[i] > 0}
    return eng.truth


__all__ = ["Engine", "Truth", "PeriodFrames", "simulate", "SQUAD"]
