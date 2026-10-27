import json
from dataclasses import dataclass, field
from pathlib import Path


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
}


def load(name_or_path: str) -> Storyline:
    if name_or_path in BUILT_IN:
        return BUILT_IN[name_or_path]
    raw = json.loads(Path(name_or_path).read_text())
    directives = [_d(d.pop("at"), d.pop("action"), **d) for d in raw.pop("directives")]
    return Storyline(directives=directives, **raw)
