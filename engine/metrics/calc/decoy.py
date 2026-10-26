"""Decoy run credit (LLD §5.6): teammates whose runs pulled defenders away from the receiver."""

from dataclasses import dataclass

import numpy as np

from engine.metrics.calc.pressure import nearest

RUN_SPEED_MS = 4.0
NEAR_RECEIVER_M = 8.0
PULLED_M = 2.0
SPACE_GAIN_M = 2.0


@dataclass
class DecoyRun:
    runner_id: str
    pulled: list[str]
    path: list[list[float]]  # runner [start, end]
    defenders: dict[str, list[list[float]]]  # opponent → [start, end]


def decoy_runs(pos: np.ndarray, speed: np.ndarray, ids: list[str], teams: list[str],
               passer: str, receiver: str) -> list[DecoyRun]:
    """Credit over a window of frames before a completed pass.

    pos (n, p, 2) and speed (n, p) are smoothed and in time order; columns follow `ids` and
    `teams`; NaN marks a player off the pitch. Credit needs all three LLD conditions.
    """
    if receiver not in ids or passer not in ids or len(pos) < 2:
        return []
    col = {pid: i for i, pid in enumerate(ids)}
    r = col[receiver]
    team = teams[r]
    first, last = pos[0], pos[-1]
    if np.isnan(first[r]).any() or np.isnan(last[r]).any():
        return []
    opp_cols = [i for i, t in enumerate(teams) if t != team]
    # Condition 3: the receiver gained space
    gain = nearest(last[r], last[opp_cols])[0][0] - nearest(first[r], first[opp_cols])[0][0]
    if not gain >= SPACE_GAIN_M:
        return []
    near_r = [i for i in opp_cols if not np.isnan(first[i]).any()
              and np.linalg.norm(first[i] - first[r]) <= NEAR_RECEIVER_M]

    runs = []
    for i, pid in enumerate(ids):
        if teams[i] != team or pid in (passer, receiver):
            continue
        if np.isnan(first[i]).any() or np.isnan(last[i]).any():
            continue
        # Condition 1: a real run
        if not np.nanmean(speed[:, i]) >= RUN_SPEED_MS:
            continue
        # Condition 2: defenders who were near the receiver moved toward where the runner went
        pulled = [o for o in near_r if not np.isnan(last[o]).any()
                  and _toward(first[o], last[o], last[i]) >= PULLED_M]
        if pulled:
            runs.append(DecoyRun(
                pid, [ids[o] for o in pulled], [_xy(first[i]), _xy(last[i])],
                {ids[o]: [_xy(first[o]), _xy(last[o])] for o in pulled}))
    return runs


def _toward(start, end, target) -> float:
    """How far a player moved from `start` to `end` in the direction of `target`."""
    to = target - start
    norm = np.linalg.norm(to)
    return float((end - start) @ to / norm) if norm > 0 else 0.0


def _xy(p) -> list[float]:
    return [round(float(p[0]), 2), round(float(p[1]), 2)]
