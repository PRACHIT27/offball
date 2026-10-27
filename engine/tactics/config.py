import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class TacticsConfig:
    window_s: float = 300.0
    refresh_s: float = 10.0
    sample_every_frames: int = 5
    event_grace_s: float = 3.0
    compare_gap_s: float = 300.0
    line_height_m: float = 6.0
    pressing_pct: float = 50.0
    pressing_min_abs: float = 1.5
    pressing_min_opp_minutes: float = 1.0
    style_points: float = 25.0
    style_min_passes: int = 25
    formation_stable_windows: int = 3
    player_position_m: float = 8.0
    tentative_s: float = 120.0
    confirmed_s: float = 300.0
    reshuffle_players: int = 3
    reshuffle_window_s: float = 300.0
    after_crux_s: float = 300.0
    buffer_max_reviews: int = 3
    buffer_per_s: float = 300.0
    buffer_quiet_s: float = 120.0
    buffer_max_hold_s: float = 300.0
    merge_within_s: float = 60.0
    confirm_due_s: float = 240.0
    long_stoppage_s: float = 90.0
    late_game_min: float = 85.0
    check_ins_min: list[int] = field(default_factory=lambda: [15, 30, 45, 60, 75, 90])
    baseline_from_min: float = 5.0
    baseline_to_min: float = 15.0
    territory_every_s: float = 60.0

    @classmethod
    def load(cls, path: str | Path | None = None) -> "TacticsConfig":
        path = path or os.environ.get("TACTICS_CONFIG")
        if not path:
            return cls()
        raw = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown tactics settings: {sorted(unknown)}")
        return cls(**raw)
