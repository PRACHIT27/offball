import numpy as np

from engine.local import run
from engine.merge.outputs import EventUpsert, FramesOut, Notice
from tests.evaluate import answer_key, score
from tests.fixturegen.generate import generate

SHORT = (180.0, 180.0)


def _frames(out):
    return {(o.batch.period, f.frame): f for o in out if isinstance(o, FramesOut)
            for f in o.batch.frames}


def _notices(out, kind):
    return [o for o in out if isinstance(o, Notice) and o.kind == kind]


def test_short_gaps_are_filled_and_long_gap_is_announced(tmp_path):
    fx = generate(tmp_path, rules=frozenset({"b_dropped"}), period_s=SHORT, halftime_s=60)
    out, pipe = run(fx.feeds_dir, "fx01")
    frames = _frames(out)
    gap = fx.mess_log["b_gap"]
    long_gap = {(1, gap["first_frame"] + i) for i in range(gap["frames"])}
    expected = {(p, f) for p, fr in fx.truth.frames.items() for f in range(len(fr.ball))}
    assert set(frames) == expected - long_gap

    filled = [k for k, f in frames.items() if f.interpolated]
    assert len(filled) == pipe.stage.counts["frames_interpolated"] > 0
    errors = []
    for period, n in filled:
        truth = fx.truth.frames[period]
        errors.append(np.hypot(*(np.array([frames[(period, n)].ball.x, frames[(period, n)].ball.y])
                                 - truth.ball[n, :2])))
    assert np.median(errors) < 0.3

    starts, ends = _notices(out, "notice.gap_start"), _notices(out, "notice.gap_end")
    assert len(starts) == len(ends) == 1
    assert starts[0].details == {"missing_frames": 50, "first_frame": gap["first_frame"]}
    assert ends[0].match_clock_ms - starts[0].match_clock_ms == 50 * 40


def test_feed_b_pause_is_flagged_and_events_keep_flowing(tmp_path):
    fx = generate(tmp_path, rules=frozenset(), period_s=SHORT, halftime_s=60,
                  pause_b=(60.0, 10.0))
    out, _ = run(fx.feeds_dir, "fx01")
    stopped = _notices(out, "notice.feed_stopped")
    resumed = _notices(out, "notice.feed_resumed")
    assert [n.details["feed"] for n in stopped] == ["B"]
    assert [n.details["feed"] for n in resumed] == ["B"]
    i, j = out.index(stopped[0]), out.index(resumed[0])
    assert any(isinstance(o, EventUpsert) for o in out[i:j]), "events must keep flowing"
    assert score(out, answer_key(fx.answer_key_dir)).recovery == 1.0


def test_no_false_alarms_on_a_clean_match(tmp_path):
    fx = generate(tmp_path, rules=frozenset(), period_s=SHORT, halftime_s=900)
    out, _ = run(fx.feeds_dir, "fx01")
    for kind in ("notice.feed_stopped", "notice.feed_resumed", "notice.gap_start"):
        assert _notices(out, kind) == []
