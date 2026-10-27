from dataclasses import asdict, dataclass, replace

import numpy as np

FORMATIONS: dict[str, list[tuple[float, float]]] = {
    "4-3-3": [(0, .1), (0, .37), (0, .63), (0, .9), (.5, .25), (.45, .5), (.5, .75),
              (1, .15), (1, .5), (1, .85)],
    "4-4-2": [(0, .1), (0, .37), (0, .63), (0, .9), (.5, .1), (.5, .37), (.5, .63), (.5, .9),
              (1, .35), (1, .65)],
    "4-4-1": [(0, .1), (0, .37), (0, .63), (0, .9), (.5, .1), (.5, .37), (.5, .63), (.5, .9),
              (.95, .5)],
    "3-5-2": [(0, .25), (0, .5), (0, .75), (.5, .05), (.45, .3), (.45, .5), (.45, .7),
              (.5, .95), (1, .35), (1, .65)],
    "3-4-2": [(0, .25), (0, .5), (0, .75), (.5, .1), (.5, .37), (.5, .63), (.5, .9),
              (1, .35), (1, .65)],
    "4-3-2": [(0, .1), (0, .37), (0, .63), (0, .9), (.5, .25), (.45, .5), (.5, .75),
              (1, .35), (1, .65)],
}
TEN_MAN = {"4-3-3": "4-4-1", "4-4-2": "4-4-1", "3-5-2": "3-4-2", "4-4-1": "4-4-1",
           "3-4-2": "3-4-2", "4-3-2": "4-3-2"}


@dataclass(frozen=True)
class TacticProfile:
    formation: str
    line_height_m: float
    press_distance_m: float
    pressers: int
    length_m: float
    width_m: float
    pass_length_pref: float
    tempo_s: float
    offside_trap: bool

    def adjusted(self, **delta) -> "TacticProfile":
        changes = {}
        for key, value in delta.items():
            if key in ("formation", "offside_trap"):
                changes[key] = value
            else:
                changes[key] = getattr(self, key) + value
        new = replace(self, **changes)
        return replace(
            new,
            line_height_m=round(float(np.clip(new.line_height_m, 22, 48)), 1),
            press_distance_m=round(float(np.clip(new.press_distance_m, 4, 18)), 1),
            pressers=int(np.clip(new.pressers, 0, 4)),
            length_m=round(float(np.clip(new.length_m, 26, 52)), 1),
            width_m=round(float(np.clip(new.width_m, 34, 62)), 1),
            pass_length_pref=round(float(np.clip(new.pass_length_pref, 0, 1)), 2),
            tempo_s=round(float(np.clip(new.tempo_s, 0.7, 2.6)), 2),
        )

    def diff(self, other: "TacticProfile") -> tuple[dict, dict]:
        a, b = asdict(self), asdict(other)
        keys = [k for k in a if a[k] != b[k]]
        return {k: a[k] for k in keys}, {k: b[k] for k in keys}

    def to_dict(self) -> dict:
        return asdict(self)


def assign_slots(current: dict[int, tuple[float, float]], formation: str) -> dict[int, int]:
    targets = FORMATIONS[formation]
    players = sorted(current, key=lambda p: (current[p][0], current[p][1]))
    order = sorted(range(len(targets)), key=lambda i: (targets[i][0], targets[i][1]))
    return {p: order[i] for i, p in enumerate(players[:len(targets)])}
