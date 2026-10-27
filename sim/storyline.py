import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class Directive:
    period: int
    at_s: float
    action: str
    team: str | None = None
    player: str | None = None
    tactics: dict | None = None
    conditions: dict | None = None
    sub_on: str | None = None


@dataclass
class Storyline:
    name: str
    match_id: str
    seed: int
    home: str
    away: str
    directives: list[Directive] = field(default_factory=list)
    start_conditions: dict = field(default_factory=lambda: {
        "weather": "clear", "temperature_c": 14, "pitch": "good"})


def clock(mmss: str) -> tuple[int, float]:
    m, s = mmss.split(":")
    total = int(m) * 60 + float(s)
    return (1, total) if total < 2700 else (2, total - 2700)


def _d(mmss: str, action: str, **kw) -> Directive:
    period, at = clock(mmss)
    return Directive(period, at, action, **kw)


BUILT_IN = {
    "red_card": Storyline("red_card", "m001", 42, "RIV", "NGU", [
        _d("23:10", "goal", team="RIV"),
        _d("46:00", "set_tactics", team="NGU",
           tactics={"formation": "3-5-2", "pressers": 1, "press_distance_m": 2}),
        _d("55:00", "conditions",
           conditions={"weather": "heavy_rain", "temperature_c": 13, "pitch": "wet"}),
        _d("60:30", "sub", team="RIV", player="RIV-09", sub_on="RIV-12"),
        _d("63:40", "stoppage", team=None, conditions={"reason": "injury", "seconds": 45}),
        _d("70:05", "red_card", team="NGU", player="NGU-04"),
        _d("75:00", "sub", team="NGU", player="NGU-10", sub_on="NGU-13"),
        _d("77:30", "goal", team="NGU"),
    ]),
    "comeback": Storyline("comeback", "m002", 7, "NGU", "KVA", [
        _d("19:40", "goal", team="KVA"),
        _d("34:10", "goal", team="KVA"),
        _d("46:00", "set_tactics", team="NGU",
           tactics={"line_height_m": 5, "pressers": 1, "press_distance_m": 3}),
        _d("58:00", "sub", team="NGU", player="NGU-08", sub_on="NGU-12"),
        _d("64:20", "goal", team="NGU"),
        _d("72:00", "sub", team="KVA", player="KVA-09", sub_on="KVA-12"),
        _d("79:50", "goal", team="NGU"),
        _d("88:15", "goal", team="NGU"),
    ]),
    "switch": Storyline("switch", "m003", 11, "KVA", "RIV", [
        _d("31:00", "goal", team="KVA"),
        _d("46:00", "set_tactics", team="RIV",
           tactics={"formation": "3-5-2", "line_height_m": 4, "pressers": 1,
                    "press_distance_m": 3}),
        _d("62:00", "conditions",
           conditions={"weather": "wind", "temperature_c": 11, "pitch": "good"}),
        _d("67:30", "goal", team="RIV"),
        _d("74:00", "sub", team="KVA", player="KVA-08", sub_on="KVA-13"),
    ]),
    "late_drama": Storyline("late_drama", "m004", 19, "KVA", "NGU", [
        _d("12:00", "goal", team="NGU"),
        _d("58:00", "set_tactics", team="KVA", tactics={"line_height_m": 6, "pressers": 1}),
        _d("66:00", "sub", team="KVA", player="KVA-10", sub_on="KVA-12"),
        _d("81:30", "red_card", team="NGU", player="NGU-05"),
        _d("86:40", "goal", team="KVA"),
        _d("90:10", "goal", team="KVA"),
    ]),
    "press_fade": Storyline("press_fade", "m005", 23, "KVA", "RIV", [
        _d("18:00", "goal", team="KVA"),
        _d("60:00", "set_tactics", team="KVA",
           tactics={"pressers": -2, "press_distance_m": -5, "line_height_m": -6}),
        _d("68:00", "sub", team="KVA", player="KVA-07", sub_on="KVA-14"),
        _d("73:20", "goal", team="RIV"),
        _d("84:00", "goal", team="RIV"),
    ]),
    "storm": Storyline("storm", "m006", 31, "NGU", "RIV", [
        _d("15:00", "conditions",
           conditions={"weather": "heavy_rain", "temperature_c": 9, "pitch": "wet"}),
        _d("38:00", "set_tactics", team="RIV",
           tactics={"pass_length_pref": 0.35, "tempo_s": -0.2}),
        _d("44:30", "stoppage", conditions={"reason": "review", "seconds": 90}),
        _d("57:00", "goal", team="NGU"),
        _d("63:00", "conditions",
           conditions={"weather": "wind", "temperature_c": 8, "pitch": "heavy"}),
        _d("70:00", "sub", team="RIV", player="RIV-10", sub_on="RIV-13"),
    ]),
}


def _mmss(total_s: float) -> str:
    return f"{int(total_s // 60):02d}:{int(total_s % 60):02d}"


def random_story(seed: int) -> Storyline:
    from sim.clubs import CLUBS

    rng = np.random.default_rng(seed)
    home, away = (str(c) for c in rng.choice(sorted(CLUBS), size=2, replace=False))
    moments: list[tuple[float, Directive]] = []

    def add(total_s: float, action: str, **kw):
        moments.append((total_s, _d(_mmss(total_s), action, **kw)))

    weather = str(rng.choice(["clear", "clear", "rain", "wind"]))
    start = {"weather": weather, "temperature_c": int(rng.integers(6, 24)),
             "pitch": "wet" if weather == "rain" else "good"}
    for _ in range(int(rng.choice([0, 1, 2, 2, 3, 3, 4, 5]))):
        add(float(rng.uniform(300, 5300)), "goal", team=str(rng.choice([home, away])))
    if rng.random() < 0.4:
        team = str(rng.choice([home, away]))
        add(float(rng.uniform(1500, 5100)), "red_card", team=team,
            player=f"{team}-{int(rng.integers(2, 12)):02d}")
    for team in (home, away):
        offs = rng.choice(range(2, 12), size=int(rng.integers(0, 4)), replace=False)
        ons = rng.choice(range(12, 18), size=len(offs), replace=False)
        for off, on in zip(offs, ons, strict=True):
            add(float(rng.uniform(3300, 5200)), "sub", team=team,
                player=f"{team}-{int(off):02d}", sub_on=f"{team}-{int(on):02d}")
    for _ in range(int(rng.integers(0, 3))):
        team = str(rng.choice([home, away]))
        change = str(rng.choice(["formation", "deeper", "higher", "press_up", "press_down",
                                 "direct"]))
        tactics = {
            "formation": {"formation": str(rng.choice(CLUBS[team].manager.preferred_formations[1:]
                                                      or ["4-4-2"]))},
            "deeper": {"line_height_m": -float(rng.uniform(6, 11))},
            "higher": {"line_height_m": float(rng.uniform(5, 9)), "pressers": 1},
            "press_up": {"pressers": 2, "press_distance_m": 4},
            "press_down": {"pressers": -2, "press_distance_m": -4},
            "direct": {"pass_length_pref": 0.3, "tempo_s": -0.3},
        }[change]
        add(float(rng.uniform(900, 5000)), "set_tactics", team=team, tactics=tactics)
    if rng.random() < 0.4:
        add(float(rng.uniform(1200, 5000)), "conditions",
            conditions={"weather": "heavy_rain", "temperature_c": start["temperature_c"],
                        "pitch": "wet"})
    if rng.random() < 0.5:
        add(float(rng.uniform(600, 5000)), "stoppage",
            conditions={"reason": str(rng.choice(["injury", "review", "crowd"])),
                        "seconds": int(rng.integers(30, 120))})
    directives = [d for _, d in sorted(moments, key=lambda m: m[0])]
    return Storyline(f"random_{seed}", f"r{seed:04d}", seed, home, away, directives, start)


def load(name_or_path: str, seed: int | None = None) -> Storyline:
    if name_or_path == "random":
        return random_story(seed if seed is not None else 1)
    if name_or_path in BUILT_IN:
        story = copy.deepcopy(BUILT_IN[name_or_path])
        if seed is not None:
            story.seed = seed
        return story
    raw = json.loads(Path(name_or_path).read_text())
    directives = [_d(d.pop("at"), d.pop("action"), **d) for d in raw.pop("directives")]
    story = Storyline(directives=directives, **raw)
    if seed is not None:
        story.seed = seed
    return story
