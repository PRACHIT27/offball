"""Pass quality, open options and decision score (LLD §5.4, §5.5)."""

from dataclasses import dataclass

import numpy as np

from engine.metrics.calc.pitch_value import pitch_value
from engine.metrics.calc.pressure import nearest, pressure

LANE_WIDTH_M = 1.5
OPEN_MIN_SPACE_M = 4.0
OPEN_MAX_DIST_M = 40.0


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def lane_opponents(start, end, opponents: np.ndarray, width: float = LANE_WIDTH_M) -> int:
    """Opponents within `width` of the segment from start to end."""
    opp = np.asarray(opponents, dtype=float).reshape(-1, 2)
    opp = opp[~np.isnan(opp).any(axis=1)]
    if not len(opp):
        return 0
    a = np.asarray(start, dtype=float)
    ab = np.asarray(end, dtype=float) - a
    denom = float(ab @ ab)
    t = np.zeros(len(opp)) if denom == 0 else np.clip((opp - a) @ ab / denom, 0.0, 1.0)
    d = np.linalg.norm(opp - (a + t[:, None] * ab), axis=1)
    return int((d <= width).sum())


def p_complete(distance: float, lane_opp: int, p_passer: float, p_receiver: float) -> float:
    return float(sigmoid(2.2 - 0.045 * distance - 0.9 * lane_opp - 0.8 * p_passer
                         - 0.6 * p_receiver))


def difficulty(p: float) -> int:
    """0–100: how unlikely the pass was to arrive."""
    return round(100 * (1 - p))


@dataclass
class Option:
    player_id: str
    x: float
    y: float
    open: bool
    p_complete: float
    value: float


def options(passer_xy, mates: dict[str, tuple[float, float]], opponents: np.ndarray,
            goal_x: float, p_passer: float) -> list[Option]:
    """Every teammate as a passing option, valued V(teammate) · p_complete (LLD §5.5)."""
    out = []
    opp = np.asarray(opponents, dtype=float).reshape(-1, 2)
    for pid, (x, y) in mates.items():
        dist = float(np.hypot(x - passer_xy[0], y - passer_xy[1]))
        space = float(nearest([(x, y)], opp)[0][0])
        lane = lane_opponents(passer_xy, (x, y), opp)
        p = p_complete(dist, lane, p_passer, float(pressure(space)))
        is_open = space >= OPEN_MIN_SPACE_M and lane == 0 and dist <= OPEN_MAX_DIST_M
        out.append(Option(pid, x, y, is_open, p, float(pitch_value(x, y, goal_x)) * p))
    return out


def decision_score(chosen: str | None, opts: list[Option]) -> tuple[float | None, Option | None]:
    """Value of the option chosen ÷ highest option value, and the best option."""
    if not opts:
        return None, None
    best = max(opts, key=lambda o: o.value)
    picked = next((o for o in opts if o.player_id == chosen), None)
    if picked is None or best.value <= 0:
        return None, best
    return round(min(picked.value / best.value, 1.0), 3), best
