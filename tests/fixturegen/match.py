"""Stand-in match model for ingestion tests. Not the real simulator (sim/).

Simple pass-and-move play at 25 Hz in clean coordinates (metres, home attacks toward x = 105),
with enough structure for the ingestion tests: kickoffs, passes with a clear ball-speed jump,
shots, fouls, cards, subs, a red card, a stoppage and a conditions change. Deterministic per seed.
"""

from dataclasses import dataclass, field

import numpy as np

from ingest.clean import FRAME_MS, PERIOD_BASE_MS

DT = FRAME_MS / 1000
HOME, AWAY = "RIV", "NGU"
CLUB_NAMES = {HOME: "Riverside Athletic", AWAY: "Northgate United"}
SQUAD = 18
# Starting slot → shirt, matching BASE_HOME (4-3-3)
SHIRTS = [1, 2, 3, 4, 5, 6, 8, 10, 7, 9, 11]
POSITIONS = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW"]
BASE_HOME = np.array(
    [[5, 34], [20, 10], [20, 26], [20, 42], [20, 58], [40, 17], [40, 34], [40, 51],
     [58, 12], [58, 34], [58, 56]], dtype=float)
BASE = np.vstack([BASE_HOME, np.column_stack([105 - BASE_HOME[:, 0], 68 - BASE_HOME[:, 1]])])
CENTRE = np.array([52.5, 34.0])
FIRST = ["Ari", "Bram", "Cato", "Dex", "Eli", "Finn", "Gus", "Hale", "Ivo", "Jory", "Kit", "Lio",
         "Milo", "Nico", "Oren", "Pax", "Quin", "Rafe"]
LAST = ["Ashby", "Brook", "Calder", "Dunmore", "Ellery", "Fenwick", "Garrow", "Hollis", "Ingram",
        "Jessop", "Kerridge", "Lowther", "Marlow", "Norland", "Oakes", "Pellow", "Quarry",
        "Rowan"]


@dataclass
class Script:
    """Scripted moments as fractions of a period, so short test matches keep them."""

    stoppage: tuple[int, float] = (1, 0.66)
    conditions_change: tuple[int, float] = (2, 0.22)
    sub_home: tuple[int, float] = (2, 0.33)
    sub_away: tuple[int, float] = (2, 0.44)
    red_card: tuple[int, float] = (2, 0.55)


@dataclass
class PeriodFrames:
    ball: np.ndarray  # (n, 3)
    pos: np.ndarray  # (n, 22, 2), NaN when the slot is empty
    codes: np.ndarray  # (n, 22) index into Truth.players, -1 when empty


@dataclass
class Truth:
    match_id: str
    players: list[str]
    prematch: dict
    events: list[dict] = field(default_factory=list)
    frames: dict[int, PeriodFrames] = field(default_factory=dict)

    def period_length_ms(self, period: int) -> int:
        return len(self.frames[period].ball) * FRAME_MS


def team_of(slot: int) -> str:
    return HOME if slot < 11 else AWAY


def attack_dir(team: str) -> float:
    return 1.0 if team == HOME else -1.0


def goal_of_opponent(team: str) -> np.ndarray:
    return np.array([105.0 if team == HOME else 0.0, 34.0])


def build_prematch(match_id: str, rng: np.random.Generator) -> dict:
    def side(club: str) -> dict:
        players = []
        for n in range(1, SQUAD + 1):
            starting_slot = SHIRTS.index(n) if n in SHIRTS else None
            players.append({
                "player_id": f"{club}-{n:02d}",
                "number": n,
                "name": f"{FIRST[rng.integers(len(FIRST))]} {LAST[rng.integers(len(LAST))]}",
                "position": POSITIONS[starting_slot] if starting_slot is not None else "SUB",
                "starting": starting_slot is not None,
            })
        return {"club_id": club, "name": CLUB_NAMES[club], "players": players}

    return {"match_id": match_id, "home": side(HOME), "away": side(AWAY)}


class _Sim:
    def __init__(self, match_id: str, rng: np.random.Generator, script: Script):
        self.rng = rng
        self.script = script
        self.match_id = match_id
        self.players = [f"{c}-{n:02d}" for c in (HOME, AWAY) for n in range(1, SQUAD + 1)]
        self.code = {p: i for i, p in enumerate(self.players)}
        self.truth = Truth(match_id, self.players, build_prematch(match_id, rng))
        self.next_event = 1
        self.slot_code = np.array(
            [self.code[f"{team_of(s)}-{SHIRTS[s % 11]:02d}"] for s in range(22)])
        self.on = np.ones(22, dtype=bool)
        self.pos = BASE.copy()

    # ---------- events ----------

    def emit(self, frame: int, type_: str, slot: int | None = None, **kw) -> dict:
        ev = {
            "event_id": f"e-{self.next_event:06d}",
            "version": 1,
            "status": "active",
            "match_id": self.match_id,
            "match_clock_ms": PERIOD_BASE_MS[self.period] + frame * FRAME_MS,
            "period": self.period,
            "type": type_,
            "team_id": team_of(slot) if slot is not None else kw.pop("team_id", None),
            "player_id": self.players[self.slot_code[slot]] if slot is not None else None,
            "target_player_id": None,
            "start": None,
            "end": None,
            "outcome": None,
            "qualifiers": [],
            "provider_xg": None,
            "details": None,
        }
        ev.update(kw)
        self.next_event += 1
        self.truth.events.append(ev)
        return ev

    @staticmethod
    def xy(p) -> dict:
        return {"x": round(float(p[0]), 2), "y": round(float(p[1]), 2)}

    # ---------- helpers ----------

    def on_team(self, team: str) -> np.ndarray:
        idx = np.arange(11) if team == HOME else np.arange(11, 22)
        return idx[self.on[idx]]

    def nearest(self, team: str, point, exclude=()) -> int:
        cands = [s for s in self.on_team(team) if s not in exclude]
        d = np.linalg.norm(self.pos[cands] - point, axis=1)
        return int(cands[int(np.argmin(d))])

    def gk(self, team: str) -> int:
        return 0 if team == HOME else 11

    def wait(self, lo: float, hi: float) -> int:
        return int(self.rng.uniform(lo, hi) / DT)

    # ---------- actions ----------

    def kick(self, f: int, to, speed: float, then, arc: float = 0.0):
        start = self.ball[:2].copy()
        dist = float(np.linalg.norm(np.asarray(to) - start))
        n = max(int(dist / speed / DT), 6)
        self.flight = {"from": start, "to": np.asarray(to, dtype=float), "f0": f, "f1": f + n,
                       "arc": arc, "then": then}
        self.carrier = None

    def give(self, slot: int, f: int, lo=1.0, hi=3.0):
        # Move the player to the ball, not the ball to the player, so receptions leave no
        # ball-speed spike that clock alignment could mistake for a pass
        self.pos[slot] = self.ball[:2] - [attack_dir(team_of(slot)) * 0.4, 0]
        self.carrier = slot
        self.next_action = f + self.wait(lo, hi)

    def act_pass(self, f: int, c: int, team: str):
        d = attack_dir(team)
        mates = [s for s in self.on_team(team) if s != c]
        rel = self.pos[mates] - self.pos[c]
        dist = np.linalg.norm(rel, axis=1)
        w = np.exp(-np.abs(dist - 15) / 10) * (1.2 + 0.6 * np.tanh(rel[:, 0] * d / 15))
        w[(dist < 5) | (dist > 45)] = 1e-6
        w[[s == self.gk(team) for s in mates]] *= 0.2
        r = mates[int(self.rng.choice(len(mates), p=w / w.sum()))]
        length = float(dist[mates.index(r)])
        success = self.rng.random() < 0.87 - 0.004 * max(0.0, length - 20)
        end = self.pos[r] + self.rng.normal(0, 0.8, 2)
        if not success:
            end = end + self.rng.normal(0, 4, 2)
        end = np.clip(end, [1, 1], [104, 67])
        long_ball = length > 30
        self.emit(f, "pass", c, target_player_id=self.players[self.slot_code[r]],
                  start=self.xy(self.ball), end=self.xy(end),
                  outcome="complete" if success else "incomplete",
                  qualifiers=["long_ball"] if long_ball else [])

        def land(f_end):
            if success:
                self.give(r, f_end)
            else:
                opp = HOME if team == AWAY else AWAY
                i = self.nearest(opp, end)
                self.emit(f_end, "interception", i, start=self.xy(end), outcome="success")
                self.give(i, f_end)

        self.receiver, self.receiver_to = r, end
        self.kick(f, end, 18.0 if long_ball else 14.0, land, arc=4.0 if long_ball else 0.0)

    def act_shot(self, f: int, c: int, team: str):
        goal = goal_of_opponent(team)
        dist = float(np.linalg.norm(goal - self.pos[c]))
        outcome = self.rng.choice(["goal", "saved", "off_target", "post"],
                                  p=[0.12, 0.35, 0.43, 0.10])
        dy = {"goal": self.rng.uniform(-3, 3), "saved": self.rng.uniform(-3, 3),
              "post": self.rng.choice([-3.66, 3.66]),
              "off_target": self.rng.choice([-1, 1]) * self.rng.uniform(5, 10)}[outcome]
        to = goal + [0, dy]
        xg = float(np.clip(0.35 * np.exp(-dist / 12) * self.rng.uniform(0.85, 1.15), 0.01, 0.9))
        self.emit(f, "shot", c, start=self.xy(self.ball), end=self.xy(to), outcome=str(outcome),
                  provider_xg=round(xg, 3))
        opp = HOME if team == AWAY else AWAY

        def land(f_end):
            if outcome == "goal":
                self.restart(f_end, self.wait(18, 22), kickoff_team=opp)
            elif outcome == "saved":
                self.give(self.gk(opp), f_end, 2, 4)
            else:
                spot = np.array([5.5 if opp == HOME else 99.5, 34.0])
                self.restart(f_end, self.wait(5, 7), slot=self.gk(opp), spot=spot)

        self.kick(f, to, 25.0, land)

    def act_take_on(self, f: int, c: int, team: str):
        opp = HOME if team == AWAY else AWAY
        defender = self.nearest(opp, self.pos[c])
        if self.rng.random() < 0.55:
            self.emit(f, "take_on", c, start=self.xy(self.ball), outcome="success")
            self.give(c, f, 1.0, 2.0)
        else:
            self.emit(f, "take_on", c, start=self.xy(self.ball), outcome="fail")
            self.emit(f + 1, "tackle", defender, start=self.xy(self.ball), outcome="success")
            self.give(defender, f + 1)

    def act_clearance(self, f: int, c: int, team: str):
        to = np.clip(self.ball[:2] + [attack_dir(team) * self.rng.uniform(35, 50),
                                      self.rng.uniform(-15, 15)], [2, 2], [103, 66])
        self.emit(f, "clearance", c, start=self.xy(self.ball), end=self.xy(to), outcome="success")

        def land(f_end):
            both = list(self.on_team(HOME)) + list(self.on_team(AWAY))
            d = np.linalg.norm(self.pos[both] - to, axis=1)
            self.give(both[int(np.argmin(d))], f_end)

        self.kick(f, to, 18.0, land, arc=8.0)

    def act_foul(self, f: int, c: int, team: str):
        opp = HOME if team == AWAY else AWAY
        fouler = self.nearest(opp, self.pos[c])
        self.emit(f, "foul", fouler, start=self.xy(self.pos[c]))
        if self.rng.random() < 0.15:
            self.emit(f + 1, "card", fouler, outcome="yellow")
        self.restart(f + 1, self.wait(7, 9), slot=c, spot=self.ball[:2].copy())

    def act(self, f: int):
        c = self.carrier
        team = team_of(c)
        goal_dist = float(np.linalg.norm(goal_of_opponent(team) - self.pos[c]))
        own_third = (self.pos[c][0] < 35) if team == HOME else (self.pos[c][0] > 70)
        r = self.rng.random()
        if self.rng.random() < 0.025:
            self.act_foul(f, c, team)
        elif goal_dist < 30 and r < 0.25:
            self.act_shot(f, c, team)
        elif r < 0.07:
            self.act_take_on(f, c, team)
        elif own_third and r < 0.12:
            self.act_clearance(f, c, team)
        else:
            self.act_pass(f, c, team)

    def restart(self, f: int, wait: int, kickoff_team=None, slot=None, spot=None):
        """Dead ball for `wait` frames, then a kickoff or a set piece from `spot`."""
        self.carrier, self.flight = None, None
        self.dead_until = f + wait
        self.after_dead = ("kickoff", kickoff_team) if kickoff_team else ("spot", slot, spot)

    def kickoff(self, f: int, team: str):
        taker = SHIRTS.index(9) + (0 if team == HOME else 11)
        if not self.on[taker]:
            taker = int(self.on_team(team)[-1])
        self.pos[taker] = CENTRE - [attack_dir(team) * 0.6, 0]
        self.ball[:] = [*CENTRE, 0.0]
        self.carrier = taker
        self.kickoff_hold = True
        self.next_action = f + 3

    # ---------- scripted moments ----------

    def scripted(self, f: int, n_frames: int):
        s = self.script
        due = [(name, frac) for name, (p, frac) in vars(s).items()
               if p == self.period and name not in self.done]
        for name, frac in due:
            if f < int(frac * n_frames) or self.flight is not None or self.dead_until > f:
                continue
            if name == "stoppage":
                self.emit(f, "stoppage_start", None, details={"stoppage_id": "s1",
                                                             "reason": "injury"})
                self.stoppage_end_at = f + self.wait(44, 46)
                self.restart(f, self.stoppage_end_at - f, slot=self.carrier,
                             spot=self.ball[:2].copy())
            elif name == "conditions_change":
                self.emit(f, "conditions", None, details={"weather": "heavy_rain",
                                                         "temperature_c": 13, "pitch": "wet"})
            elif name in ("sub_home", "sub_away"):
                team, off_no, on_no = (HOME, 9, 12) if name == "sub_home" else (AWAY, 10, 13)
                slot = SHIRTS.index(off_no) + (0 if team == HOME else 11)
                if slot == self.carrier or not self.on[slot]:
                    continue
                self.emit(f, "sub_off", slot)
                self.slot_code[slot] = self.code[f"{team}-{on_no:02d}"]
                self.emit(f, "sub_on", slot)
            elif name == "red_card":
                slot = 11 + SHIRTS.index(4)
                if slot == self.carrier:
                    continue
                self.emit(f, "card", slot, outcome="red")
                self.on[slot] = False
            self.done.add(name)
        if self.stoppage_end_at == f:
            self.emit(f, "stoppage_end", None, details={"stoppage_id": "s1", "reason": "injury"})

    # ---------- main loop ----------

    def move_players(self, possession: str | None):
        bx, by = self.ball[0], self.ball[1]
        target = BASE.copy()
        target[:, 0] += 0.5 * (bx - 52.5)
        target[:, 1] += 0.25 * (by - 34)
        if possession:
            idx = np.arange(11) if possession == HOME else np.arange(11, 22)
            target[idx, 0] += 6 * attack_dir(possession)
        for g in (0, 11):
            target[g] = [BASE[g, 0] + 0.1 * (bx - 52.5), 34 + 0.2 * (by - 34)]
        if self.carrier is not None and not self.kickoff_hold:
            c = self.carrier
            target[c] = self.pos[c] + [attack_dir(team_of(c)) * 3, 0]
            opp = HOME if team_of(c) == AWAY else AWAY
            presser = self.nearest(opp, self.pos[c])
            target[presser] = self.pos[c] - 1.5 * attack_dir(opp) * np.array([1, 0])
        if self.flight is not None and self.receiver is not None:
            target[self.receiver] = self.receiver_to
        if self.kickoff_hold:
            target[self.carrier] = self.pos[self.carrier]
        delta = target - self.pos
        dist = np.linalg.norm(delta, axis=1, keepdims=True)
        speed = np.clip(0.8 * dist, 0, 7.0)
        step = np.where(dist > 1e-6, delta / np.maximum(dist, 1e-6) * np.minimum(dist, speed * DT),
                        0)
        self.pos = np.clip(self.pos + step, [0.5, 0.5], [104.5, 67.5])

    def run_period(self, period: int, length_s: float, kickoff_team: str) -> PeriodFrames:
        self.period = period
        n = int(length_s / DT)
        self.pos = BASE.copy()
        self.ball = np.array([*CENTRE, 0.0])
        self.carrier, self.flight, self.receiver = None, None, None
        self.dead_until, self.after_dead, self.kickoff_hold = -1, None, False
        self.done, self.stoppage_end_at = set(), -1
        balls = np.zeros((n, 3))
        poss = np.full((n, 22, 2), np.nan)
        codes = np.full((n, 22), -1, dtype=np.int16)

        self.emit(0, "period_start", None)
        if period == 1:
            self.emit(0, "conditions", None, details={"weather": "clear", "temperature_c": 14,
                                                     "pitch": "good"})
        self.kickoff(0, kickoff_team)

        for f in range(n):
            if f == n - 1:
                self.emit(f, "period_end", None)
            self.scripted(f, n)
            if self.dead_until == f:
                kind = self.after_dead
                if kind[0] == "kickoff":
                    self.kickoff(f, kind[1])
                else:
                    _, slot, spot = kind
                    slot = slot if slot is not None and self.on[slot] else self.gk(HOME)
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
                if f >= self.next_action:
                    self.kickoff_hold = False
                    self.act(f)
                elif not self.kickoff_hold:
                    c = self.carrier
                    self.ball[:2] = self.pos[c] + [attack_dir(team_of(c)) * 0.4, 0]

            possession = team_of(self.carrier) if self.carrier is not None else None
            self.move_players(possession)
            balls[f] = self.ball
            poss[f, self.on] = self.pos[self.on]
            codes[f, self.on] = self.slot_code[self.on]
        return PeriodFrames(balls, poss, codes)


def simulate(match_id: str = "fx01", seed: int = 42, period_s=(2790.0, 2880.0),
             script: Script | None = None) -> Truth:
    rng = np.random.default_rng(seed)
    sim = _Sim(match_id, rng, script or Script())
    for period, length in zip((1, 2), period_s, strict=True):
        sim.truth.frames[period] = sim.run_period(period, length, HOME if period == 1 else AWAY)
    return sim.truth
