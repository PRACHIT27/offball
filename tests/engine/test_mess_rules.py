"""Ingestion LLD §11 "Each mess rule": turned on alone, its fix restores the truth."""

import numpy as np
import pytest

from engine.local import run
from engine.merge.outputs import FramesOut
from tests.evaluate import answer_key, score
from tests.fixturegen.generate import generate
from tests.fixturegen.mess import FULL, LIGHT

SHORT = (240.0, 240.0)
# Position tolerance for frames, per rule (noise is ±10 cm on each axis)
FRAME_TOL_M = {"b_noise": 0.15}


def _check_frames(out, fx, rule):
    frames = {(o.batch.period, f.frame): f for o in out if isinstance(o, FramesOut)
              for f in o.batch.frames}
    expected = {(p, n) for p, fr in fx.truth.frames.items() for n in range(len(fr.ball))}
    if rule == "b_dropped":
        gap = fx.mess_log["b_gap"]
        expected -= {(1, gap["first_frame"] + i) for i in range(gap["frames"])}
    assert set(frames) == expected
    tol = FRAME_TOL_M.get(rule, 0.006)
    worst = 0.0
    for (period, n), f in frames.items():
        if f.interpolated:
            continue  # checked in test_frames_health
        truth = fx.truth.frames[period]
        worst = max(worst, float(np.max(np.abs([f.ball.x, f.ball.y] - truth.ball[n, :2]))))
    assert worst <= tol, worst


@pytest.mark.parametrize("rule", sorted(LIGHT))
def test_light_rule_alone_is_fixed(tmp_path, rule):
    fx = generate(tmp_path, rules=frozenset({rule}), period_s=SHORT, halftime_s=60)
    out, pipe = run(fx.feeds_dir, "fx01")
    s = score(out, answer_key(fx.answer_key_dir))
    assert s.recovery == 1.0, s.missing[:10]
    assert s.extra_active == []
    assert pipe.dead_letters == []
    assert abs(pipe.stage.offset_ms - fx.clock_offset_ms) <= 80
    _check_frames(out, fx, rule)


@pytest.mark.parametrize("rule", sorted(FULL - LIGHT))
def test_full_rule_alone_is_fixed(tmp_path, rule):
    fx = generate(tmp_path, rules=frozenset({rule}), period_s=SHORT, halftime_s=60)
    out, pipe = run(fx.feeds_dir, "fx01")
    s = score(out, answer_key(fx.answer_key_dir))
    assert s.extra_active == []
    if rule == "a_broken":
        # Broken records are dead-lettered with their reason; the match carries on (FR-10)
        broken = fx.mess_log["a_broken"]
        assert sorted(s.missing) == sorted(broken)
        assert sorted(d.stage for d in pipe.dead_letters) == ["map_ids", "parse", "validate"]
        assert all(d.reason and d.body for d in pipe.dead_letters)
    else:
        assert s.recovery == 1.0, s.missing[:10]
        assert pipe.dead_letters == []
    if rule == "a_out_of_order":
        assert pipe.stage.counts["late_inserts"] >= 1
    if rule == "b_wrong_units":
        assert pipe.stage.counts["units_fixed"] == len(fx.mess_log["b_wrong_units"])
    _check_frames(out, fx, rule)


def test_full_mess_all_rules_together(tmp_path):
    fx = generate(tmp_path, mess_level="full", period_s=SHORT, halftime_s=60)
    out, pipe = run(fx.feeds_dir, "fx01")
    s = score(out, answer_key(fx.answer_key_dir))
    lost = len(fx.mess_log["a_broken"])
    assert s.recovered >= s.true_total - lost and s.extra_active == []
    assert abs(pipe.stage.offset_ms - fx.clock_offset_ms) <= 80
