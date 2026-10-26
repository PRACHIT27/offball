import hashlib
import json

import pytest
from pydantic import ValidationError

from ingest.raw import FeedBBatch, feed_a_adapter
from tests.fixturegen.generate import generate

SHORT = (180.0, 180.0)


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("full"), mess_level="full", period_s=SHORT,
                    halftime_s=60)


def test_same_seed_same_feeds(tmp_path):
    digests = []
    for run in ("a", "b"):
        fx = generate(tmp_path / run, mess_level="light", period_s=SHORT, halftime_s=60)
        digests.append([hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(fx.feeds_dir.iterdir())])
    assert digests[0] == digests[1]


def test_feed_messages_validate_except_broken_ones(full):
    a_bad = 0
    for line in _lines(full.feeds_dir / "feed_a.jsonl"):
        try:
            feed_a_adapter.validate_json(line["body"])
        except ValidationError:
            a_bad += 1
    # Unknown player IDs are valid JSON for the schema; they fail at ID mapping instead
    assert 1 <= a_bad <= len(full.mess_log["a_broken"])
    for line in _lines(full.feeds_dir / "feed_b.jsonl"):
        FeedBBatch.model_validate_json(line["body"])


def test_feeds_never_carry_answer_key_fields(full):
    text = (full.feeds_dir / "feed_a.jsonl").read_text()
    for field in ("true_", "answer", "clock_offset", "event_id"):
        assert field not in text
    assert not list(full.feeds_dir.glob("*answer*"))


def test_every_message_has_headers(full):
    for name in ("feed_a.jsonl", "feed_b.jsonl"):
        for line in _lines(full.feeds_dir / name):
            assert set(line["properties"]) == {"emitted_at", "feed", "match_id"}


def test_off_level_has_no_mess(tmp_path):
    fx = generate(tmp_path, mess_level="off", period_s=SHORT, halftime_s=60)
    assert fx.clock_offset_ms == 0 and fx.mess_log == {}
    a = _lines(fx.feeds_dir / "feed_a.jsonl")
    assert len(a) == len(fx.truth.events) + 2  # + prematch and lineup
