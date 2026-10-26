"""On Azure the two normalizers run independently, so one feed can reach the engine seconds
behind the other (cold start, backlog). Alignment and recovery must not depend on that."""

from dataclasses import replace

import pytest

from engine.local import Pipeline, messages
from tests.evaluate import answer_key, score
from tests.fixturegen.generate import generate


@pytest.mark.parametrize("lagging,lag_s", [("B", 8), ("B", 45), ("A", 8), ("A", 45)])
def test_one_feed_arriving_late_changes_nothing(tmp_path, lagging, lag_s):
    fx = generate(tmp_path, mess_level="light", period_s=(240.0, 240.0), halftime_s=60)
    arrived = sorted((replace(m, wall_ms=m.wall_ms + (lag_s * 1000 if m.feed == lagging else 0))
                      for m in messages(fx.feeds_dir)), key=lambda m: m.wall_ms)
    pipe, out = Pipeline("fx01"), []
    for m in arrived:
        out += pipe.process(m)
    out += pipe.stage.flush(arrived[-1].wall_ms)
    s = score(out, answer_key(fx.answer_key_dir))
    assert s.recovery == 1.0, s.missing[:10]
    assert abs(pipe.stage.offset_ms - fx.clock_offset_ms) <= 80
