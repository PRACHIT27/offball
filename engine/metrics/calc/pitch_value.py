"""Pitch value V(x, y) for any spot (LLD §5.3), used to compare passing options."""

import numpy as np

from ingest.clean import PITCH_LENGTH_M, PITCH_WIDTH_M

GOAL_HALF_WIDTH = 3.66
DECAY_M = 18.0


def attack_x(team_id: str, home_id: str) -> float:
    """x of the goal a team attacks. Home always attacks toward x = 105 (flip done at ingest)."""
    return PITCH_LENGTH_M if team_id == home_id else 0.0


def pitch_value(x, y, goal_x: float):
    """0–1: high close to goal and with a wide view of the goal mouth."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    cy = PITCH_WIDTH_M / 2
    dist = np.hypot(goal_x - x, cy - y)
    a1 = np.arctan2(cy - GOAL_HALF_WIDTH - y, np.abs(goal_x - x))
    a2 = np.arctan2(cy + GOAL_HALF_WIDTH - y, np.abs(goal_x - x))
    angle = np.abs(a2 - a1)
    return np.clip(np.exp(-dist / DECAY_M) * (0.4 + 0.6 * angle / 1.2), 0.0, 1.0)
