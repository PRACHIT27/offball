import pytest
from pydantic import ValidationError

from ingest.clean import CleanEvent
from ingest.raw import FeedAEvent, FeedBBatch, feed_a_adapter

PASS = {
    "msgType": "event", "matchId": "m001", "eventId": 4512, "version": 1, "typeId": 1,
    "periodId": 1, "timeSec": 730.62, "teamId": 101, "playerId": 50707, "outcome": 1,
    "x": 45.8, "y": 32.9, "qualifiers": [{"qualifierId": 140, "value": "67.6"}], "xG": None,
}


def test_feed_a_event_parses_by_msg_type():
    msg = feed_a_adapter.validate_python(PASS)
    assert isinstance(msg, FeedAEvent)
    assert msg.qualifiers[0].qualifierId == 140


@pytest.mark.parametrize(
    "change",
    [{"x": 120.0}, {"periodId": 3}, {"eventId": 0}, {"unexpected": 1}, {"msgType": "goal"}],
)
def test_feed_a_rejects_broken_records(change):
    with pytest.raises(ValidationError):
        feed_a_adapter.validate_python(PASS | change)


def test_feed_b_batch_parses():
    batch = FeedBBatch.model_validate({
        "msgType": "frames", "matchId": "m001", "batchSeq": 3651, "periodId": 1,
        "periodStartFrame": 1000,
        "frames": [{"frameIdx": 19255, "ball": [-210, 340, 25],
                    "home": [[7, 1200, -1580]], "away": [[4, -830, 410]]}],
    })
    assert batch.frames[0].home[0] == (7, 1200.0, -1580.0)


def test_clean_event_id_format():
    with pytest.raises(ValidationError):
        CleanEvent(event_id="4512", version=1, match_id="m001", match_clock_ms=0, period=1,
                   type="pass", source_ids={}, emitted_at="2026-10-25T00:00:00.000Z")
