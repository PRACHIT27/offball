"""Frame processor (LLD §5.1, §5.2, §5.9) on a hand-built run."""

import numpy as np
import pytest

from engine.metrics.models import Cue, MetricDoc, PressureSample, StatsMessage
from tests.metrics.scenes import batches, engine, frame, run

STILL = {"RIV-01": (5.0, 34.0), "NGU-04": (30.0, 60.0), "NGU-01": (100.0, 34.0)}


def sprint_run():
    """RIV-07 jogs 20 s at 5 m/s, sprints 2 s at 8 m/s, then 1 s at 9.5 m/s (an alert)."""
    speeds = [5.0] * 500 + [8.0] * 50 + [9.5] * 25 + [0.0] * 50
    x, frames = 10.0, []
    for n, v in enumerate(speeds):
        x += v * 0.04
        frames.append(frame(n, STILL | {"RIV-07": (x, 20.0)}, ball=(x + 0.4, 20.0, 0.1)))
    return frames, sum(speeds) * 0.04


@pytest.fixture(scope="module")
def ran():
    e = engine()
    frames, true_distance = sprint_run()
    out = run(e, batches(frames))
    return e, out, true_distance


def test_distance_speed_sprints_top_speed(ran):
    e, _, true_distance = ran
    c = e.roster.col["RIV-07"]
    t = e.totals
    assert t.distance[c] == pytest.approx(true_distance, rel=0.01)
    assert t.sprints[c] == 1
    assert t.top_speed[c] == pytest.approx(9.5, abs=0.1)
    assert t.distance[e.roster.col["RIV-01"]] == 0.0


def test_fast_sprint_alert_once(ran):
    _, out, _ = ran
    alerts = [o for o in out if isinstance(o, Cue) and o.kind == "speed_alert"]
    assert len(alerts) == 1
    a = alerts[0]
    assert a.data["player_id"] == "RIV-07" and a.data["type"] == "fast"
    assert a.data["speed_kmh"] >= 32 and a.status == "on_air" and a.caption_source == "none"
    assert a.evidence.frames


def test_positions_every_batch_with_name_tags(ran):
    _, out, _ = ran
    pos = [o for o in out if isinstance(o, StatsMessage) and o.kind == "positions"]
    assert len(pos) == 625 // 5
    last = pos[-1].values
    assert len(last["frames"]) == 5 and set(last["frames"][0]["players"]) >= {"RIV-07"}
    assert last["tags"]["RIV-07"]["distance_m"] > 100
    mid = pos[len(pos) // 4].values["tags"]["RIV-07"]
    assert mid["speed_ms"] == pytest.approx(5.0, abs=0.05)


def test_totals_and_heatmap_every_10_seconds(ran):
    e, out, _ = ran
    totals = [o for o in out if isinstance(o, StatsMessage) and o.kind == "player_totals"]
    assert [m.match_clock_ms for m in totals] == [10_000, 20_000]
    docs = [o for o in out if isinstance(o, MetricDoc) and o.body["player_id"] == "RIV-07"]
    assert [d.id for d in docs] == ["player:RIV-07:10000", "player:RIV-07:20000"]
    assert docs[-1].body["frames_on"] > 0 and docs[-1].body["avg_position"][1] == 20.0
    heat = [o for o in out if isinstance(o, StatsMessage) and o.kind == "heatmap"
            and o.team_id == "RIV"]
    grid = np.array(heat[-1].values["players"]["RIV-07"]["match"])
    assert grid.shape == (21, 14) and grid.sum() == pytest.approx(1.0, abs=0.01)
    assert heat[-1].values["players"]["RIV-02"]["match"] is None  # never on the pitch


def test_pressure_on_the_carrier_goes_to_tactics(ran):
    _, out, _ = ran
    samples = [o for o in out if isinstance(o, PressureSample)]
    assert samples and all(s.carrier_id == "RIV-07" for s in samples)
    assert samples[0].pressure == 0.0 and samples[0].presser_id in ("NGU-04", "NGU-01")


def test_pressure_ring_values():
    e = engine()
    frames = [frame(n, {"RIV-07": (50.0, 34.0), "NGU-04": (52.0, 34.0)}) for n in range(10)]
    out = run(e, batches(frames))
    tags = [o for o in out if isinstance(o, StatsMessage) and o.kind == "positions"][-1]
    assert tags.values["tags"]["RIV-07"]["pressure"] == pytest.approx(0.75)


def test_jump_in_position_is_not_running():
    e = engine()
    frames = [frame(n, {"RIV-07": (50.0 if n < 50 else 70.0, 34.0)}) for n in range(100)]
    run(e, batches(frames))
    c = e.roster.col["RIV-07"]
    assert e.totals.distance[c] == 0.0 and e.totals.top_speed[c] == 0.0


def test_stray_player_ids_beyond_the_roster_are_dropped_not_fatal():
    from engine.metrics.memory import MAX_PLAYERS

    e = engine()
    crowd = {f"ZZZ-{i:03d}": (50.0, 34.0) for i in range(MAX_PLAYERS + 10)}
    frames = [frame(n, crowd | {"RIV-07": (10.0 + 0.2 * n, 20.0)}) for n in range(50)]
    run(e, batches(frames))  # must not raise
    assert len(e.roster.ids) == MAX_PLAYERS and e.roster.dropped > 0
    assert e.totals.distance[e.roster.col["RIV-07"]] > 0  # listed in the prematch: kept
