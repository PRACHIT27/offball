"""Provider writers: turn the truth into Feed A and Feed B messages (ingestion LLD §13)."""

from dataclasses import dataclass

import numpy as np

from ingest.clean import FRAME_MS, PERIOD_BASE_MS
from tests.fixturegen.match import AWAY, HOME, SQUAD, Truth

TEAM_IDS = {HOME: 101, AWAY: 202}
TYPE_IDS = {"pass": 1, "take_on": 3, "foul": 4, "tackle": 7, "interception": 8, "clearance": 12,
            "card": 17, "sub_off": 18, "sub_on": 19, "period_end": 30, "period_start": 32,
            "conditions": 90, "stoppage_start": 91, "stoppage_end": 92}
SHOT_TYPE_IDS = {"off_target": 13, "post": 14, "saved": 15, "goal": 16}
SUCCESS = {"complete": 1, "success": 1, "incomplete": 0, "fail": 0}
BATCH = 5
PROVIDER_FIRST_FRAME = 1000


@dataclass
class Msg:
    """One provider message. `emitted_ms` is wall time relative to kickoff."""

    emitted_ms: float
    feed: str
    body: dict | str
    tag: str = ""


def provider_player_id(player_id: str) -> int:
    club, number = player_id.split("-")
    return 50000 + (100 if club == HOME else 200) + int(number)


@dataclass
class Clock:
    """Maps (period, match clock) to wall time at 1× speed."""

    period1_ms: int
    halftime_ms: int

    def wall(self, period: int, clock_ms: float) -> float:
        if period == 1:
            return clock_ms
        return self.period1_ms + self.halftime_ms + (clock_ms - PERIOD_BASE_MS[2])


def to_grid(point: dict, period: int) -> tuple[float, float]:
    """Clean metres (home → +x) to feed A's absolute 0–100 grid (teams switch ends at half)."""
    x, y = point["x"], point["y"]
    if period == 2:
        x, y = 105 - x, 68 - y
    return round(x / 1.05, 1), round(y / 0.68, 1)


def feed_a_event(ev: dict, offset_ms: int) -> dict:
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
        body["teamId"] = TEAM_IDS[ev["team_id"]]
    if ev["player_id"]:
        body["playerId"] = provider_player_id(ev["player_id"])
    if ev["outcome"] in SUCCESS:
        body["outcome"] = SUCCESS[ev["outcome"]]
    if ev["start"]:
        body["x"], body["y"] = to_grid(ev["start"], period)
    quals = []
    if ev["end"]:
        ex, ey = to_grid(ev["end"], period)
        quals += [{"qualifierId": 140, "value": str(ex)}, {"qualifierId": 141, "value": str(ey)}]
    if t == "pass":
        quals.append(
            {"qualifierId": 7, "value": str(provider_player_id(ev["target_player_id"]))})
        if "long_ball" in ev["qualifiers"]:
            quals.append({"qualifierId": 1, "value": "1"})
    if t == "card":
        quals.append({"qualifierId": 31, "value": ev["outcome"]})
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
    mid = truth.match_id
    msgs = [
        Msg(-120_000, "A", {"msgType": "prematch", "matchId": mid, "prematch": truth.prematch},
            "prematch"),
        Msg(-119_000, "A", {
            "msgType": "lineup", "matchId": mid,
            "teams": [{"teamId": TEAM_IDS[club], "side": side,
                       "players": [{"playerId": provider_player_id(f"{club}-{n:02d}"), "shirt": n}
                                   for n in range(1, SQUAD + 1)]}
                      for club, side in ((HOME, "home"), (AWAY, "away"))]}, "lineup"),
    ]
    for ev in truth.events:
        emitted = clock.wall(ev["period"], ev["match_clock_ms"]) + 300
        msgs.append(Msg(emitted, "A", feed_a_event(ev, offset_ms), ev["event_id"]))
    return msgs


def feed_b(truth: Truth, clock: Clock, rng: np.random.Generator, noise_cm: float) -> list[Msg]:
    msgs = []
    period_start = {1: PROVIDER_FIRST_FRAME,
                    2: PROVIDER_FIRST_FRAME + (clock.period1_ms + clock.halftime_ms) // FRAME_MS}
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
        shirts = np.array([int(p.split("-")[1]) for p in truth.players])
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
