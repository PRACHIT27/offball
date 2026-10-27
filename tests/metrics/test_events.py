"""Event processor (LLD §5.4–5.8): passes and shots, read against the frames around them."""

import pytest

from engine.metrics.models import Cue, MetricDoc, PassValues, StatsMessage
from tests.metrics.scenes import batches, engine, event, frame, run, upsert

PLAYERS = {"RIV-07": (50.0, 34.0), "RIV-09": (70.0, 34.0), "RIV-11": (60.0, 10.0),
           "NGU-05": (52.0, 36.0), "NGU-04": (60.0, 50.0)}
PASS_AT = 100


def pass_frames(n_frames: int = 200, speed: float = 15.0):
    """The ball sits at RIV-07's feet, then travels to RIV-09 at `speed` m/s from frame 100."""
    frames = []
    bx = 50.4
    for n in range(n_frames):
        if n > PASS_AT:
            bx = min(70.0, bx + speed * 0.04)
        frames.append(frame(n, PLAYERS, ball=(bx, 34.0, 0.1)))
    return frames


def a_pass(version=1, outcome="complete", target="RIV-09"):
    return event("e-000100", "pass", PASS_AT, "RIV-07", version=version, start=(50.4, 34.0),
                 end=(70.0, 34.0), target_player_id=target, outcome=outcome)


def of(out, cls, kind=None):
    return [o for o in out if isinstance(o, cls) and (kind is None or o.kind == kind)]


def test_pass_waits_for_its_frames_then_computes():
    e = engine()
    frames = batches(pass_frames())
    early = run(e, frames[:21])  # up to frame 104: not 0.3 s past the pass yet
    early += e.dispatch(upsert(a_pass()))
    assert not of(early, StatsMessage, "pass")
    out = run(e, frames[21:])
    [msg] = of(out, StatsMessage, "pass")
    v = msg.values
    assert msg.player_id == "RIV-07" and msg.evidence.event_ids == ["e-000100"]
    assert msg.evidence.frames == [PASS_AT]
    assert v["distance_m"] == pytest.approx(19.6)
    assert v["speed_ms"] == pytest.approx(15.0, abs=0.3)
    assert v["pressure_passer"] == pytest.approx((5 - 8 ** 0.5) / 4, abs=0.01)
    assert v["lane_opponents"] == 0
    assert v["open_options"] == 2
    assert 0 <= v["difficulty"] <= 100
    assert v["decision_score"] == 1.0 and msg.best_option["player_id"] == "RIV-09"
    assert v["value_gain"] > 0

    [arc] = of(out, Cue, "pass_arc")
    assert arc.status == "on_air" and arc.data["receiver_id"] == "RIV-09"
    assert not of(out, Cue, "best_option")  # chose the best option
    [doc] = of(out, MetricDoc)[-1:]
    assert doc.id == "event:e-000100:1" and doc.body["completed"] is True
    [values] = of(out, PassValues)
    assert values.passer_id == "RIV-07" and values.completed and values.value_gain > 0

    c = e.roster.col["RIV-07"]
    assert (e.totals.passes[c], e.totals.passes_completed[c]) == (1, 1)


def test_poor_choice_shows_the_best_option():
    e = engine()
    run(e, batches(pass_frames()))
    out = e.dispatch(upsert(event("e-000101", "pass", PASS_AT, "RIV-07", start=(50.4, 34.0),
                                  end=(60.0, 10.0), target_player_id="RIV-11",
                                  outcome="complete")))
    [msg] = of(out, StatsMessage, "pass")
    assert msg.values["decision_score"] < 0.4
    [ghost] = of(out, Cue, "best_option")
    assert ghost.data["best"]["player_id"] == "RIV-09" and ghost.data["chosen_id"] == "RIV-11"


def test_shot_speed_xg_and_range():
    e = engine()
    frames = []
    bx = 90.0
    for n in range(200):
        if n > PASS_AT:
            bx = min(105.0, bx + 28.0 * 0.04)
        frames.append(frame(n, PLAYERS | {"RIV-09": (89.6, 34.0)}, ball=(bx, 34.0, 0.3)))
    run(e, batches(frames))
    out = e.dispatch(upsert(event("e-000200", "shot", PASS_AT, "RIV-09", start=(90.0, 34.0),
                                  end=(105.0, 34.5), outcome="saved", provider_xg=0.35)))
    [shot] = of(out, StatsMessage, "shot")
    assert shot.values["speed_ms"] == pytest.approx(28.0, abs=0.5)
    assert shot.values["xg"] == 0.35 and shot.values["big_chance"] is True
    [xg] = of(out, StatsMessage, "xg")
    assert xg.team_id == "RIV" and xg.values["range"] == [0, 1]
    assert xg.values["text"] == "0–1 goals expected, mostly from 1 big chance"
    assert {c.kind for c in of(out, Cue)} == {"shot_speed", "xg_summary"}


def test_other_events_produce_nothing():
    e = engine()
    run(e, batches(pass_frames()))
    assert e.dispatch(upsert(event("e-000300", "foul", PASS_AT, "NGU-05"))) == []
