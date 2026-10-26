"""Pressure on one player at one moment (LLD §5.2)."""

import numpy as np


def pressure(d):
    """1 at ≤ 1 m from the nearest opponent, 0 at ≥ 5 m."""
    return np.clip((5.0 - np.asarray(d, dtype=float)) / 4.0, 0.0, 1.0)


def nearest(points: np.ndarray, others: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance from each point (n, 2) to its nearest other (m, 2), and that other's index.

    NaN rows in `others` (players off the pitch) are ignored; with no others the distance is inf.
    """
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    others = np.asarray(others, dtype=float).reshape(-1, 2)
    others = others[~np.isnan(others).any(axis=1)] if len(others) else others
    if not len(others):
        return np.full(len(points), np.inf), np.full(len(points), -1)
    d = np.linalg.norm(points[:, None, :] - others[None, :, :], axis=2)
    idx = np.argmin(d, axis=1)
    return d[np.arange(len(points)), idx], idx
