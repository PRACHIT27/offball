import pytest

from engine.local import run
from tests.evaluate import answer_key, score
from tests.fixturegen.generate import generate

TOLERANCE_MS = 80


@pytest.mark.parametrize("seed", [42, 7, 11])
def test_clock_offset_is_recovered_within_80_ms(tmp_path, seed):
    fx = generate(tmp_path, seed=seed, rules=frozenset({"a_clock_offset", "b_noise"}),
                  period_s=(300.0, 300.0), halftime_s=60)
    out, pipe = run(fx.feeds_dir, "fx01")
    assert 500 <= fx.clock_offset_ms <= 2000
    assert abs(pipe.stage.offset_ms - fx.clock_offset_ms) <= TOLERANCE_MS
    assert len(pipe.stage.clock.anchors) == 30
    assert score(out, answer_key(fx.answer_key_dir)).recovery >= 0.99


def test_no_offset_estimates_zero(tmp_path):
    fx = generate(tmp_path, rules=frozenset(), period_s=(120.0, 120.0), halftime_s=30)
    _, pipe = run(fx.feeds_dir, "fx01")
    assert abs(pipe.stage.offset_ms) <= 40
