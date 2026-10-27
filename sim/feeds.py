import numpy as np

from ingest.clean import FRAME_MS, PERIOD_BASE_MS
from sim.clubs import SQUAD
from sim.engine import Truth
from tests.fixturegen.providers import (
    BATCH,
    PROVIDER_FIRST_FRAME,
    SHOT_TYPE_IDS,
    SUCCESS,
    TYPE_IDS,
    Clock,
    Msg,
    to_grid,
)

SIDE_TEAM_IDS = {"home": 101, "away": 202}
REASON_QUALIFIERS = {"late_tackle": 301, "from_behind": 302, "holding": 303, "pushing": 304,
                     "reckless_challenge": 311, "serious_foul_play": 312,
                     "denying_goal_chance": 313, "second_yellow": 314, "tactical_foul": 315}


class Sides:
    def __init__(self, truth: Truth):
        self.side = {truth.home: "home", truth.away: "away"}

    def team_id(self, club: str) -> int:
        return SIDE_TEAM_IDS[self.side[club]]

    def player_id(self, player_id: str) -> int:
        club, number = player_id.split("-")
        return 50000 + (100 if self.side[club] == "home" else 200) + int(number)


def feed_a_event(ev: dict, offset_ms: int, sides: Sides) -> dict:
    period = ev["period"]
    t = ev["type"]
    body = {
        "msgType": "event", "matchId": ev["match_id"], "eventId": int(ev["event_id"][2:]),
        "version": ev["version"],
        "typeId": SHOT_TYPE_IDS[ev["outcome"]] if t == "shot" else TYPE_IDS[t],
        "periodId": period,
        "timeSec": round((ev["match_clock_ms"] - PERIOD_BASE_MS[period] + offset_ms) / 1000, 3),
    }
    if ev["team_id"]:
        body["teamId"] = sides.team_id(ev["team_id"])
    if ev["player_id"]:
        body["playerId"] = sides.player_id(ev["player_id"])
    if ev["outcome"] in SUCCESS:
        body["outcome"] = SUCCESS[ev["outcome"]]
    if ev["start"]:
        body["x"], body["y"] = to_grid(ev["start"], period)
    quals = []
    if ev["end"]:
        ex, ey = to_grid(ev["end"], period)
        quals += [{"qualifierId": 140, "value": str(ex)}, {"qualifierId": 141, "value": str(ey)}]
    if t == "pass":
        quals.append({"qualifierId": 7, "value": str(sides.player_id(ev["target_player_id"]))})
        if "long_ball" in ev["qualifiers"]:
            quals.append({"qualifierId": 1, "value": "1"})
    if t == "card":
        quals.append({"qualifierId": 31, "value": ev["outcome"]})
    for reason in ev["qualifiers"]:
        if reason in REASON_QUALIFIERS:
            quals.append({"qualifierId": REASON_QUALIFIERS[reason], "value": "1"})
    if quals:
        body["qualifiers"] = quals
    if t == "shot":
        body["xG"] = ev["provider_xg"]
    if t == "conditions":
        d = ev["details"]
        body["conditions"] = {"weather": d["weather"], "temperatureC": d["temperature_c"],
                              "pitch": d["pitch"]}
    if t in ("stoppage_start", "stoppage_end"):
        body["stoppageId"] = ev["details"]["stoppage_id"]
        body["reason"] = ev["details"]["reason"]
    return body


def feed_a(truth: Truth, clock: Clock, offset_ms: int) -> list[Msg]:
    sides = Sides(truth)
    mid = truth.match_id
    msgs = [
        Msg(-120_000, "A", {"msgType": "prematch", "matchId": mid, "prematch": truth.prematch},
            "prematch"),
        Msg(-119_000, "A", {
            "msgType": "lineup", "matchId": mid,
            "teams": [{"teamId": sides.team_id(club), "side": side,
                       "players": [{"playerId": sides.player_id(f"{club}-{n:02d}"), "shirt": n}
                                   for n in range(1, SQUAD + 1)]}
                      for club, side in ((truth.home, "home"), (truth.away, "away"))]},
            "lineup"),
    ]
    for ev in truth.events:
        emitted = clock.wall(ev["period"], ev["match_clock_ms"]) + 300
        msgs.append(Msg(emitted, "A", feed_a_event(ev, offset_ms, sides), ev["event_id"]))
    return msgs


def feed_b(truth: Truth, clock: Clock, rng: np.random.Generator, noise_cm: float) -> list[Msg]:
    msgs = []
    period_start = {1: PROVIDER_FIRST_FRAME,
                    2: PROVIDER_FIRST_FRAME + (clock.period1_ms + clock.halftime_ms) // FRAME_MS}
    shirts = np.array([int(p.split("-")[1]) for p in truth.players])
    seq = 0
    for period, fr in truth.frames.items():
        sign = 1 if period == 1 else -1
        n = len(fr.ball)
        ball_cm = np.column_stack([sign * (fr.ball[:, 0] - 52.5) * 100,
                                   sign * (fr.ball[:, 1] - 34) * 100, fr.ball[:, 2] * 100])
        pos_cm = np.stack([sign * (fr.pos[..., 0] - 52.5) * 100,
                           sign * (fr.pos[..., 1] - 34) * 100], axis=-1)
        if noise_cm:
            ball_cm[:, :2] += rng.uniform(-noise_cm, noise_cm, (n, 2))
            pos_cm += rng.uniform(-noise_cm, noise_cm, pos_cm.shape)
        ball_cm = np.rint(ball_cm).astype(int)
        pos_cm = np.rint(np.nan_to_num(pos_cm)).astype(int)
        for b0 in range(0, n, BATCH):
            frames = []
            for f in range(b0, min(b0 + BATCH, n)):
                sides = {"home": [], "away": []}
                for slot in np.flatnonzero(fr.codes[f] >= 0):
                    code = fr.codes[f, slot]
                    side = "home" if slot < 11 else "away"
                    sides[side].append([int(shirts[code]), int(pos_cm[f, slot, 0]),
                                        int(pos_cm[f, slot, 1])])
                frames.append({"frameIdx": period_start[period] + f,
                               "ball": [int(v) for v in ball_cm[f]], **sides})
            last = min(b0 + BATCH, n) - 1
            emitted = clock.wall(period, PERIOD_BASE_MS[period] + last * FRAME_MS) + FRAME_MS
            msgs.append(Msg(emitted, "B", {
                "msgType": "frames", "matchId": truth.match_id, "batchSeq": seq,
                "periodId": period, "periodStartFrame": period_start[period], "frames": frames,
            }, f"b{seq}"))
            seq += 1
    return msgs
