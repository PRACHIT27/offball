"""xG range and chance story (LLD §5.8). xG itself comes from the provider (feed A)."""

import numpy as np

BIG_CHANCE_XG = 0.3


def goal_distribution(xgs: list[float]) -> np.ndarray:
    """P(total goals = k) with every shot an independent chance (exact, by dynamic programming)."""
    dist = np.array([1.0])
    for p in xgs:
        dist = np.append(dist * (1 - p), 0.0) + np.append(0.0, dist * p)
    return dist


def percentile(dist: np.ndarray, q: float) -> int:
    """Smallest number of goals k with P(goals ≤ k) ≥ q."""
    return int(np.searchsorted(np.cumsum(dist), q - 1e-12))


def xg_range(xgs: list[float]) -> tuple[int, int]:
    """10th–90th percentile of total goals."""
    dist = goal_distribution(xgs)
    return percentile(dist, 0.10), percentile(dist, 0.90)


def chance_story(xgs: list[float]) -> dict:
    total = float(sum(xgs))
    big = [x for x in xgs if x >= BIG_CHANCE_XG]
    lo, hi = xg_range(xgs)
    share = sum(big) / total if total else 0.0
    goals = f"{lo} goal{'s' if lo != 1 else ''}" if lo == hi else f"{lo}–{hi} goals"
    text = f"{goals} expected"
    if big:
        text += f", {'mostly ' if share >= 0.5 else ''}from {len(big)} big " \
                f"chance{'s' if len(big) != 1 else ''}"
    return {"shots": len(xgs), "total_xg": round(total, 2), "range": [lo, hi],
            "big_chances": len(big), "big_chance_share": round(share, 2), "text": text}
