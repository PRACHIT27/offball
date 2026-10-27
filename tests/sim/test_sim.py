import copy
import hashlib
import json

import numpy as np
import pytest

from engine.local import run_local
from ingest.raw import FeedBBatch, feed_a_adapter
from sim.output import generate
from sim.storyline import BUILT_IN, Directive, Storyline

SHORT = (180.0, 180.0)


def short_story() -> Storyline:
    return Storyline("short", "t001", 5, "RIV", "NGU", [
        Directive(1, 60.0, "conditions",
                  conditions={"weather": "heavy_rain", "temperature_c": 12, "pitch": "wet"}),
        Directive(2, 30.0, "sub", team="RIV", player="RIV-09", sub_on="RIV-12"),
        Directive(2, 60.0, "red_card", team="NGU", player="NGU-04"),
    ])


@pytest.fixture(scope="module")
def short(tmp_path_factory):
    return generate(short_story(), tmp_path_factory.mktemp("short"), "light", period_s=SHORT,
                    halftime_s=60)


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    return generate(copy.deepcopy(BUILT_IN["red_card"]), tmp_path_factory.mktemp("full"), "light")


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_same_seed_same_feeds(tmp_path):
    digests = []
    for run in ("a", "b"):
        m = generate(short_story(), tmp_path / run, "light", period_s=SHORT, halftime_s=60)
        digests.append([hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(m.feeds_dir.iterdir())])
    assert digests[0] == digests[1]


def test_feeds_validate_against_ingestion_schemas(short):
    for line in _lines(short.feeds_dir / "feed_a.jsonl"):
        feed_a_adapter.validate_json(line["body"])
    for line in _lines(short.feeds_dir / "feed_b.jsonl"):
        FeedBBatch.model_validate_json(line["body"])


def test_feeds_never_leak_hidden_truth(short):
    lines = _lines(short.feeds_dir / "feed_a.jsonl")
    everything = "\n".join(line["body"] for line in lines)
    for field in ("abilities", "answer", "true_", "stamina", "event_id", "tactic_changes"):
        assert field not in everything
    live = "\n".join(line["body"] for line in lines if '"msgType":"prematch"' not in line["body"])
    for field in ("line_height", "pressers", "formation"):
        assert field not in live
    assert not list(short.feeds_dir.glob("*answer*"))


def test_red_card_follows_match_rules_and_triggers_reaction(short):
    ev = short.truth.events
    reds = [e for e in ev if e["type"] == "card" and e["outcome"] == "red"]
    assert len(reds) == 1 and reds[0]["player_id"] == "NGU-04"
    after = short.truth.frames[2].codes[-1]
    assert int(np.sum(after[11:] >= 0)) == 10
    rules = [c["cause"]["rule"] for c in short.truth.tactic_changes if c["team_id"] == "NGU"]
    assert "on_red_card" in rules


def test_answer_key_has_tactic_changes_and_player_stats(short):
    key = json.loads((short.answer_key_dir / "answer_key.json").read_text())
    assert key["tactic_changes"]
    change = key["tactic_changes"][0]
    assert {"at_clock_ms", "team_id", "cause", "before", "after"} <= set(change)
    assert key["true_player_stats"]["RIV-07"]["distance_m"] > 0


@pytest.mark.slow
def test_full_match_is_football_realistic(full):
    ev = full.truth.events
    for team in ("RIV", "NGU"):
        passes = [e for e in ev if e["type"] == "pass" and e["team_id"] == team]
        acc = sum(e["outcome"] == "complete" for e in passes) / len(passes)
        shots = [e for e in ev if e["type"] == "shot" and e["team_id"] == team]
        assert 350 <= len(passes) <= 800
        assert 0.74 <= acc <= 0.9
        assert 4 <= len(shots) <= 20
    goals = sum(full.truth.score.values())
    assert 1 <= goals <= 6
    stats = full.truth.true_player_stats
    full_game = [s for p, s in stats.items() if not p.endswith("-01") and s["distance_m"] > 8000]
    km = np.median([s["distance_m"] for s in full_game]) / 1000
    assert 9 <= km <= 12.5
    assert max(s["top_speed_ms"] for s in stats.values()) <= 10.0


def _line_height(truth, team, period, f0, f1):
    fr = truth.frames[period]
    slots = list(range(11)) if team == truth.home else list(range(11, 22))
    mine = 0 if team == truth.home else 1
    mask = (fr.possession[f0:f1] >= 0) & (fr.possession[f0:f1] != mine)
    x = fr.pos[f0:f1, slots, 0][mask]
    depth = x if team == truth.home else 105 - x
    return float(np.nanmedian(np.nanmean(np.sort(depth[:, 1:], axis=1)[:, :4], axis=1)))


@pytest.mark.slow
def test_red_card_line_drop_is_detectable(full):
    red = next(e for e in full.truth.events if e["type"] == "card" and e["outcome"] == "red")
    f = (red["match_clock_ms"] - 2_700_000) // 40
    before = _line_height(full.truth, "NGU", 2, f - 25 * 300, f)
    after = _line_height(full.truth, "NGU", 2, f + 25 * 60, f + 25 * 360)
    assert before - after >= 6


@pytest.mark.slow
def test_ingestion_recovers_the_simulated_match(full, tmp_path):
    r = run_local(full.feeds_dir, tmp_path / "silver", full.truth.match_id)
    store = r.store
    latest = {}
    for doc in store.events.values():
        if doc["event_id"] not in latest or doc["version"] > latest[doc["event_id"]]["version"]:
            latest[doc["event_id"]] = doc
    active = {k for k, d in latest.items() if d["status"] == "active"}
    truth_ids = {e["event_id"] for e in full.truth.events}
    assert len(active & truth_ids) / len(truth_ids) >= 0.99
    assert not store.dead_letters
    assert abs(r.counts["clock_offset_ms"] - full.clock_offset_ms) <= 80
