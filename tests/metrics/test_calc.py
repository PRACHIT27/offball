"""LLD §5 calculations on hand-built inputs (LLD §9: open options, decoy credit, xG range)."""

import numpy as np
import pytest

from engine.metrics.calc.decoy import decoy_runs
from engine.metrics.calc.pass_model import (
    decision_score,
    difficulty,
    lane_opponents,
    options,
    p_complete,
)
from engine.metrics.calc.pitch_value import attack_x, pitch_value
from engine.metrics.calc.pressure import nearest, pressure
from engine.metrics.calc.xg_range import chance_story, goal_distribution, xg_range


def test_pressure_is_one_close_and_zero_far():
    assert pressure([0.5, 1.0, 3.0, 5.0, 9.0]).tolist() == [1.0, 1.0, 0.5, 0.0, 0.0]


def test_nearest_ignores_players_off_the_pitch():
    d, idx = nearest([(0, 0)], np.array([[np.nan, np.nan], [3, 4]]))
    assert d[0] == 5.0 and idx[0] == 0
    assert nearest([(0, 0)], np.empty((0, 2)))[0][0] == np.inf


def test_pitch_value_rises_toward_goal_and_centre():
    gx = attack_x("RIV", "RIV")
    assert gx == 105.0 and attack_x("NGU", "RIV") == 0.0
    assert pitch_value(95, 34, gx) > pitch_value(70, 34, gx) > pitch_value(30, 34, gx)
    assert pitch_value(95, 34, gx) > pitch_value(95, 5, gx)
    assert 0 <= pitch_value(104, 34, gx) <= 1


def test_lane_counts_only_opponents_near_the_segment():
    opp = np.array([[10, 0.5], [10, 3], [25, 0], [-3, 0]])
    assert lane_opponents((0, 0), (20, 0), opp) == 1


def test_difficulty_rises_with_distance_lane_and_pressure():
    easy = p_complete(10, 0, 0, 0)
    assert p_complete(40, 0, 0, 0) < easy
    assert p_complete(10, 2, 0, 0) < easy
    assert p_complete(10, 0, 1, 1) < easy
    assert difficulty(easy) < difficulty(p_complete(40, 2, 1, 1))


def test_open_options_and_best_option_in_a_hand_built_scene():
    passer = (50, 34)
    mates = {"RIV-09": (75, 34),  # open, forward: best
             "RIV-04": (40, 34),  # open, backward
             "RIV-11": (70, 10),  # marked (opponent 1 m away)
             "RIV-02": (95, 60)}  # too far (> 40 m)
    opps = np.array([[71, 10], [30, 60], [60, 55]])
    opts = options(passer, mates, opps, 105.0, p_passer=0.0)
    by = {o.player_id: o for o in opts}
    assert sum(o.open for o in opts) == 2
    assert by["RIV-09"].open and by["RIV-04"].open
    assert not by["RIV-11"].open and not by["RIV-02"].open
    score, best = decision_score("RIV-04", opts)
    assert best.player_id == "RIV-09"
    assert 0 < score < 1
    assert decision_score("RIV-09", opts)[0] == 1.0


def _decoy_scene(runner_speed: float):
    """RIV-09 runs across; NGU-04 follows him away from the receiver RIV-10."""
    n, dt = 75, 0.04
    t = np.arange(n) * dt
    ids = ["RIV-08", "RIV-10", "RIV-09", "NGU-04", "NGU-05"]
    teams = ["RIV", "RIV", "RIV", "NGU", "NGU"]
    pos = np.zeros((n, 5, 2))
    pos[:, 0] = (50, 34)  # passer
    pos[:, 1] = (70, 34)  # receiver, standing
    pos[:, 2, 0] = 72
    pos[:, 2, 1] = 36 + runner_speed * t  # runner moving away along y
    follow = min(runner_speed, 3.0)
    pos[:, 3, 0] = 72
    pos[:, 3, 1] = 35 + follow * t  # defender follows the runner
    pos[:, 4] = (90, 10)
    speed = np.zeros((n, 5))
    speed[:, 2] = runner_speed
    speed[:, 3] = follow
    return pos, speed, ids, teams


def test_decoy_run_earns_credit():
    runs = decoy_runs(*_decoy_scene(6.0), passer="RIV-08", receiver="RIV-10")
    assert [(r.runner_id, r.pulled) for r in runs] == [("RIV-09", ["NGU-04"])]


def test_standing_teammate_earns_no_credit():
    pos, speed, ids, teams = _decoy_scene(6.0)
    speed[:, 2] = 0.5  # same positions, but not a run
    assert decoy_runs(pos, speed, ids, teams, "RIV-08", "RIV-10") == []


def test_goal_distribution_is_exact():
    assert goal_distribution([0.5, 0.5]).tolist() == pytest.approx([0.25, 0.5, 0.25])
    assert goal_distribution([]).tolist() == [1.0]


@pytest.mark.parametrize("xgs, expected", [
    ([], (0, 0)),
    ([0.05] * 4, (0, 1)),
    ([0.9, 0.9], (1, 2)),
    ([0.5], (0, 1)),
    ([0.76] * 10, (6, 9)),
])
def test_xg_range_percentiles(xgs, expected):
    assert xg_range(xgs) == expected


def test_chance_story():
    story = chance_story([0.45, 0.35, 0.05, 0.04])
    assert story["big_chances"] == 2 and story["range"] == [0, 2]
    assert story["text"] == "0–2 goals expected, mostly from 2 big chances"
