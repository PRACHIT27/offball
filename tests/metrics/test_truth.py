"""PM-27 truth comparison (LLD §9): distance ±3%, top speed ±0.3 m/s, sprints ±2 against the
fixture's true frames. Evaluation only: reads answer-keys/, which the live path never does."""

import numpy as np
import pytest

from engine.metrics.frame_processor import SPRINT_FRAMES, SPRINT_MS
from engine.metrics.local import run_metrics
from engine.metrics.memory import DT, MAX_PLAUSIBLE_MS
from engine.metrics.totals import TOP_HOLD_FRAMES
from tests.evaluate import answer_key
from tests.fixturegen.generate import generate

SHORT = (240.0, 240.0)
# The stand-in fixture match changes speed instantly (e.g. a keeper from 2.4 to 7.0 m/s in one
# frame for 0.44 s). No player can: the real simulator caps acceleration at 5 m/s². A plateau
# that short and sudden is blurred by the 0.2 s smoothing, so those top speeds aren't compared.
MAX_HUMAN_ACCEL = 10.0


def true_stats(key_dir) -> dict[str, dict]:
    """Distance, top speed and sprints from the true 25 Hz positions, with the same definitions
    as the metrics (jumps faster than a footballer can run are not running)."""
    key = answer_key(key_dir)
    npz = np.load(key_dir / key["frames_file"])
    players = key["players"]
    stats = {p: {"distance_m": 0.0, "top_speed_ms": 0.0, "sprints": 0, "instant_top": False}
             for p in players}
    for period in (1, 2):
        pos, codes = npz[f"pos_{period}"].astype(float), npz[f"codes_{period}"]
        for slot in range(pos.shape[1]):
            for code in set(codes[:, slot].tolist()) - {-1}:
                xy = np.where((codes[:, slot] == code)[:, None], pos[:, slot], np.nan)
                speed = np.linalg.norm(np.diff(xy, axis=0), axis=1) / DT
                speed[speed > MAX_PLAUSIBLE_MS] = np.nan
                s = stats[players[code]]
                s["distance_m"] += float(np.nansum(speed) * DT)
                v = np.nan_to_num(speed)
                held = np.lib.stride_tricks.sliding_window_view(v, TOP_HOLD_FRAMES).min(axis=1)
                i = int(held.argmax())
                if held[i] > s["top_speed_ms"]:
                    s["top_speed_ms"] = float(held[i])
                    accel = np.abs(np.diff(v[max(0, i - 2):i + TOP_HOLD_FRAMES + 2])) / DT
                    s["instant_top"] = bool(accel.max(initial=0) > MAX_HUMAN_ACCEL)
                fast = np.concatenate([[0], (v >= SPRINT_MS).astype(int), [0]])
                runs = np.diff(np.flatnonzero(np.diff(fast)))[::2]
                s["sprints"] += int((runs >= SPRINT_FRAMES).sum())
    return stats


@pytest.fixture(scope="module")
def compared(tmp_path_factory):
    root = tmp_path_factory.mktemp("truth")
    fx = generate(root, mess_level="off", period_s=SHORT, halftime_s=60)
    e, _ = run_metrics(fx.feeds_dir, root / "out", "fx01")
    truth = true_stats(fx.answer_key_dir)
    ours = {pid: {"distance_m": float(e.totals.distance[c]),
                  "top_speed_ms": float(e.totals.top_speed[c]),
                  "sprints": int(e.totals.sprints[c])} for pid, c in e.roster.col.items()}
    return ours, {p: s for p, s in truth.items() if s["distance_m"] > 0}


def test_distance_within_3_percent(compared):
    ours, truth = compared
    off = {p: ours[p]["distance_m"] / t["distance_m"] - 1 for p, t in truth.items()
           if t["distance_m"] > 100}
    assert off and max(abs(v) for v in off.values()) <= 0.03, off


def test_top_speed_within_0_3(compared):
    ours, truth = compared
    human = {p: t for p, t in truth.items() if not t["instant_top"]}
    assert len(human) >= len(truth) // 2
    off = {p: ours[p]["top_speed_ms"] - t["top_speed_ms"] for p, t in human.items()}
    assert max(abs(v) for v in off.values()) <= 0.3, off


def test_sprints_within_2(compared):
    ours, truth = compared
    off = {p: ours[p]["sprints"] - t["sprints"] for p, t in truth.items()}
    assert max(abs(v) for v in off.values()) <= 2, off
