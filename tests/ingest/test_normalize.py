import json

import numpy as np
import pytest

from ingest.clean import NormalizedEvent, NormalizedFrames
from ingest.normalize import normalize_a, normalize_b
from tests.fixturegen.generate import generate

NOW = "2026-10-25T14:00:00.000Z"


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture(scope="module")
def clean_fixture(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("off"), mess_level="off", period_s=(120.0, 120.0),
                    halftime_s=30)


@pytest.fixture(scope="module")
def normalized(clean_fixture):
    sheet, events, frames, dead = None, [], [], []
    for line in _lines(clean_fixture.feeds_dir / "feed_a.jsonl"):
        r = normalize_a(line["body"], line["properties"], sheet, NOW)
        sheet = r.teamsheet or sheet
        events += [o.event for o in r.outputs if isinstance(o, NormalizedEvent)]
        dead += r.dead_letters
    for line in _lines(clean_fixture.feeds_dir / "feed_b.jsonl"):
        r = normalize_b(line["body"], line["properties"], sheet, NOW)
        frames += [o.batch for o in r.outputs if isinstance(o, NormalizedFrames)]
        dead += r.dead_letters
    return sheet, events, frames, dead


def test_clean_feeds_produce_no_dead_letters(normalized):
    assert normalized[3] == []


def test_feed_a_events_match_truth(clean_fixture, normalized):
    events = {e.event_id: e for e in normalized[1]}
    truth = clean_fixture.truth.events
    assert set(events) == {t["event_id"] for t in truth}
    for t in truth:
        e = events[t["event_id"]]
        assert (e.type, e.team_id, e.player_id, e.target_player_id, e.outcome, e.period) == (
            t["type"], t["team_id"], t["player_id"], t["target_player_id"], t["outcome"],
            t["period"])
        assert e.match_clock_ms == t["match_clock_ms"]
        for key in ("start", "end"):
            if t[key]:
                got = getattr(e, key)
                assert abs(got.x - t[key]["x"]) < 0.06 and abs(got.y - t[key]["y"]) < 0.04
        assert e.details == t["details"]
        assert e.qualifiers == t["qualifiers"]


def test_feed_b_frames_match_truth(clean_fixture, normalized):
    truth = clean_fixture.truth
    for batch in normalized[2]:
        fr = truth.frames[batch.period]
        for f in batch.frames:
            assert np.allclose([f.ball.x, f.ball.y], fr.ball[f.frame, :2], atol=0.006)
            for p in f.players:
                slot = int(np.flatnonzero(fr.codes[f.frame] == truth.players.index(p.player_id))[0])
                assert np.allclose([p.x, p.y], fr.pos[f.frame, slot], atol=0.006)


def test_second_half_positions_are_flipped(normalized):
    # Home always attacks toward x = 105: home goalkeeper stays near x = 0 in both halves
    for batch in normalized[2]:
        gk = next(p for p in batch.frames[0].players if p.player_id == "RIV-01")
        assert gk.x < 20, (batch.period, gk.x)


PROPS = {"emitted_at": NOW, "feed": "A", "match_id": "fx01"}


@pytest.mark.parametrize("body,stage", [
    ('{"msgType": "event", "matchId"', "parse"),
    ('{"msgType": "event", "matchId": "fx01"}', "validate"),
])
def test_broken_feed_a_records_are_dead_lettered(body, stage, normalized):
    r = normalize_a(body, PROPS, normalized[0], NOW)
    assert r.outputs == [] and r.dead_letters[0].stage == stage
    assert r.dead_letters[0].match_id == "fx01" and r.dead_letters[0].body == body


def _event(**change):
    body = {"msgType": "event", "matchId": "fx01", "eventId": 7, "version": 1, "typeId": 1,
            "periodId": 1, "timeSec": 1.0, "teamId": 101, "playerId": 50107, "outcome": 1,
            "x": 50.0, "y": 50.0}
    return json.dumps(body | change)


@pytest.mark.parametrize("change,stage", [
    ({"playerId": 99999}, "map_ids"),
    ({"teamId": 303}, "map_ids"),
    ({"typeId": 77}, "map_types"),
])
def test_unmappable_feed_a_records_are_dead_lettered(change, stage, normalized):
    r = normalize_a(_event(**change), PROPS, normalized[0], NOW)
    assert r.dead_letters and r.dead_letters[0].stage == stage


def test_event_before_lineup_is_dead_lettered():
    r = normalize_a(_event(), PROPS, None, NOW)
    assert r.dead_letters[0].stage == "map_ids"


def test_unknown_shirt_in_feed_b_is_dead_lettered(normalized):
    body = json.dumps({"msgType": "frames", "matchId": "fx01", "batchSeq": 1, "periodId": 1,
                       "periodStartFrame": 0,
                       "frames": [{"frameIdx": 3, "ball": [0, 0, 0], "home": [[77, 0, 0]],
                                   "away": []}]})
    r = normalize_b(body, PROPS | {"feed": "B"}, normalized[0], NOW)
    assert r.dead_letters[0].stage == "map_ids"
