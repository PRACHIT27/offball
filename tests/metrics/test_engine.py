"""Whole engine on a fixture match: delay (LLD §3, §9), restart from a snapshot, local mode."""

import json
import time
from collections import defaultdict

import numpy as np
import pytest

from engine.local import Pipeline, messages
from engine.metrics.local import run_metrics
from engine.metrics.router import MetricsEngine
from tests.fixturegen.generate import generate

SHORT = (240.0, 240.0)


@pytest.fixture(scope="module")
def fixture_match(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("fx"), mess_level="light", period_s=SHORT,
                    halftime_s=60)


def clean_messages(fx) -> list:
    pipe, out, last = Pipeline("fx01"), [], 0.0
    for msg in messages(fx.feeds_dir):
        out += pipe.process(msg)
        last = msg.wall_ms
    return out + pipe.stage.flush(last)


def test_delay_frame_batch_20ms_event_50ms(fixture_match):
    e = MetricsEngine("fx01")
    took = defaultdict(list)
    for clean in clean_messages(fixture_match):
        t0 = time.perf_counter()
        e.dispatch(clean)
        took[clean.kind].append(time.perf_counter() - t0)
    assert np.percentile(took["frames"], 99) <= 0.020
    assert max(took["event.upsert"]) <= 0.050


def test_restart_from_snapshot_keeps_totals(fixture_match):
    msgs = clean_messages(fixture_match)
    straight = MetricsEngine("fx01")
    for m in msgs:
        straight.dispatch(m)
    straight.flush()

    half = len(msgs) // 2
    first = MetricsEngine("fx01")
    for m in msgs[:half]:
        first.dispatch(m)
    resumed = MetricsEngine.from_state(json.loads(json.dumps(first.to_state())))
    for m in msgs[half:]:
        resumed.dispatch(m)
    resumed.flush()

    a, b = straight.totals, resumed.totals
    for name in ("passes", "passes_completed", "shots", "sprints"):
        assert getattr(a, name).tolist() == getattr(b, name).tolist(), name
    assert np.allclose(a.xg, b.xg)
    # Memory refills from the replayed frames, so a few frames of movement are lost
    assert np.allclose(a.distance, b.distance, rtol=0.005, atol=1.0)
    assert resumed.cues.next_no >= first.cues.next_no


def test_local_mode_writes_stats_cues_and_metrics(fixture_match, tmp_path):
    e, pub = run_metrics(fixture_match.feeds_dir, tmp_path, "fx01")
    out = tmp_path / "metrics" / "fx01"
    stats = [json.loads(line) for line in (out / "stats.jsonl").open()]
    cues = [json.loads(line) for line in (out / "cues.jsonl").open()]
    docs = json.loads((out / "metrics.json").read_text())
    assert {s["kind"] for s in stats} >= {"positions", "player_totals", "heatmap", "pass",
                                          "shot", "xg"}
    assert {c["kind"] for c in cues} >= {"pass_arc", "shot_speed", "xg_summary"}
    assert all(c["evidence"]["event_ids"] or c["evidence"]["frames"] for c in cues)
    assert all(s["evidence"]["event_ids"] or s["evidence"]["frames"] for s in stats)
    assert any(k.startswith("player:") for k in docs) and any(k.startswith("event:") for k in docs)
    # The fixture's light mess corrects or deletes some events: their cues come back withdrawn
    assert pub.counts["stats.pass"] > 50
