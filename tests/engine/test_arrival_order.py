"""On Azure the two normalizers run independently, so one feed can reach the engine seconds
behind the other (cold start, backlog). Alignment and recovery must not depend on that."""

from dataclasses import replace

import pytest

from engine.local import Pipeline, messages
from tests.evaluate import answer_key, score
from tests.fixturegen.generate import generate


@pytest.mark.parametrize("lagging,lag_s,speed", [
    ("B", 8, 1), ("B", 45, 1), ("A", 8, 1), ("A", 45, 1),
    ("B", 8, 10),  # seen on Azure: 10x replay, feed B normalizer cold start
])
def test_one_feed_arriving_late_changes_nothing(tmp_path, lagging, lag_s, speed):
    fx = generate(tmp_path, mess_level="light", period_s=(240.0, 240.0), halftime_s=60)
    msgs = list(messages(fx.feeds_dir))
    t0 = msgs[0].wall_ms
    arrived = sorted((replace(m, wall_ms=t0 + (m.wall_ms - t0) / speed
                              + (lag_s * 1000 if m.feed == lagging else 0)) for m in msgs),
                     key=lambda m: m.wall_ms)
    pipe, out = Pipeline("fx01"), []
    for m in arrived:
        out += pipe.process(m)
    out += pipe.stage.flush(arrived[-1].wall_ms)
    s = score(out, answer_key(fx.answer_key_dir))
    assert s.recovery == 1.0, s.missing[:10]
    assert abs(pipe.stage.offset_ms - fx.clock_offset_ms) <= 80


def test_without_feed_b_events_are_released_after_the_give_up_time(tmp_path):
    from engine.merge.outputs import EventUpsert
    from engine.merge.stage import NO_ANCHOR_GIVE_UP_MS

    fx = generate(tmp_path, rules=frozenset(), period_s=(120.0, 120.0), halftime_s=30)
    a_only = [m for m in messages(fx.feeds_dir) if m.feed == "A"]
    pipe, out = Pipeline("fx01"), []
    first_event = None
    for m in a_only:
        got = pipe.process(m)
        if first_event is None and got and any(isinstance(o, EventUpsert) for o in got):
            first_event = m.wall_ms
        out += got
    held_since = pipe.stage.held_since
    assert held_since is not None
    # Nothing before the give-up time; everything once the engine's timer passes it
    assert first_event is None or first_event - held_since >= NO_ANCHOR_GIVE_UP_MS
    out += pipe.stage.tick(a_only[-1].wall_ms + NO_ANCHOR_GIVE_UP_MS)
    released = {o.event.event_id for o in out if isinstance(o, EventUpsert)}
    assert released == {e["event_id"] for e in fx.truth.events}
