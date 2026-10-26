"""Running totals per player, one column per player as in the roster (LLD §5.1, §5.4, §5.9).

Shared by the frame and event processors; snapshotted every 10 s of match time (LLD §7).
"""

import numpy as np

from engine.metrics.memory import MAX_PLAYERS
from ingest.clean import PITCH_LENGTH_M, PITCH_WIDTH_M

TOP_HOLD_FRAMES = 10  # top speed must be held ≥ 0.4 s
HEAT_COLS, HEAT_ROWS = 21, 14
CELL_X, CELL_Y = PITCH_LENGTH_M / HEAT_COLS, PITCH_WIDTH_M / HEAT_ROWS
RECENT_MINUTES = 15

ARRAYS = {
    "distance": float, "sprints": int, "top_speed": float, "run_frames": int,
    "fast_alerted": bool, "milestone_done": bool, "sum_x": float, "sum_y": float,
    "frames_on": int, "passes": int, "passes_completed": int, "expected_completed": float,
    "shots": int, "xg": float,
}


class Totals:
    def __init__(self) -> None:
        for name, dtype in ARRAYS.items():
            setattr(self, name, np.zeros(MAX_PLAYERS, dtype=dtype))
        self.held = np.zeros((TOP_HOLD_FRAMES, MAX_PLAYERS))
        self.heat = np.zeros((MAX_PLAYERS, HEAT_COLS, HEAT_ROWS), dtype=np.int32)
        # minute of match time → frame counts in that minute, for the last-15-minutes map
        self.heat_by_minute: dict[int, np.ndarray] = {}

    def add_heat(self, clock_ms: int, xy: np.ndarray) -> None:
        on = ~np.isnan(xy).any(axis=1)
        cols = np.flatnonzero(on)
        if not len(cols):
            return
        cx = np.clip((xy[cols, 0] // CELL_X).astype(int), 0, HEAT_COLS - 1)
        cy = np.clip((xy[cols, 1] // CELL_Y).astype(int), 0, HEAT_ROWS - 1)
        self.heat[cols, cx, cy] += 1
        minute = clock_ms // 60_000
        grid = self.heat_by_minute.get(minute)
        if grid is None:
            grid = self.heat_by_minute[minute] = np.zeros_like(self.heat)
            for old in [m for m in self.heat_by_minute if m <= minute - RECENT_MINUTES]:
                del self.heat_by_minute[old]
        grid[cols, cx, cy] += 1

    def recent_heat(self) -> np.ndarray:
        if not self.heat_by_minute:
            return np.zeros_like(self.heat)
        return np.sum(list(self.heat_by_minute.values()), axis=0)

    def to_state(self) -> dict:
        s = {name: getattr(self, name).tolist() for name in ARRAYS}
        s["held"] = self.held.tolist()
        s["heat"] = self.heat.tolist()
        s["heat_by_minute"] = {str(m): g.tolist() for m, g in self.heat_by_minute.items()}
        return s

    @classmethod
    def from_state(cls, state: dict) -> "Totals":
        t = cls()
        for name, dtype in ARRAYS.items():
            setattr(t, name, np.array(state[name], dtype=dtype))
        t.held = np.array(state["held"], dtype=float)
        t.heat = np.array(state["heat"], dtype=np.int32)
        t.heat_by_minute = {int(m): np.array(g, dtype=np.int32)
                            for m, g in state["heat_by_minute"].items()}
        return t
