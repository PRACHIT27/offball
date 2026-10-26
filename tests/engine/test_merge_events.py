from collections import Counter

import pytest

from engine.local import Pipeline, messages, run
from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, Notice
from engine.merge.stage import MergeStage
from tests.evaluate import answer_key, final_events, score
from tests.fixturegen.generate import generate

SHORT = (180.0, 180.0)


def _run(tmp_path, *rules):
    fx = generate(tmp_path, rules=frozenset(rules), period_s=SHORT, halftime_s=60)
    out, pipe = run(fx.feeds_dir, "fx01")
    return fx, out, pipe


def _upserts(out):
    return [o for o in out if isinstance(o, EventUpsert)]


def test_clean_feed_recovers_everything_in_order(tmp_path):
    fx, out, _ = _run(tmp_path)
    s = score(out, answer_key(fx.answer_key_dir))
    assert s.recovery == 1.0 and s.extra_active == []
    ups = _upserts(out)
    assert not any(u.late for u in ups)
    keys = [(u.event.period, u.event.match_clock_ms) for u in ups]
    assert keys == sorted(keys)


def test_duplicates_are_dropped(tmp_path):
    fx, out, pipe = _run(tmp_path, "a_duplicates")
    emitted = Counter((u.event.event_id, u.event.version) for u in _upserts(out))
    assert max(emitted.values()) == 1
    assert pipe.stage.counts["duplicates"] == fx.mess_log["a_duplicates"]
    assert score(out, answer_key(fx.answer_key_dir)).recovery == 1.0


def test_late_corrections_keep_same_id_with_higher_version(tmp_path):
    fx, out, _ = _run(tmp_path, "a_corrections")
    latest = final_events(out)
    for event_id in fx.mess_log["a_corrections"]:
        assert latest[event_id].version == 2
    notices = [o for o in out if isinstance(o, Notice) and o.kind == "notice.correction_applied"]
    assert notices, "corrections after release must be announced (FR-19)"
    assert score(out, answer_key(fx.answer_key_dir)).recovery == 1.0


def test_deleted_events_are_marked_deleted(tmp_path):
    fx, out, _ = _run(tmp_path, "a_deletions")
    latest = final_events(out)
    for event_id in fx.mess_log["a_deletions"]:
        assert latest[event_id].status == "deleted"
    assert any(isinstance(o, EventDelete) for o in out)
    s = score(out, answer_key(fx.answer_key_dir))
    assert s.recovery == 1.0 and s.extra_active == []


def test_out_of_order_events_are_reordered_or_late_inserted(tmp_path):
    fx, out, pipe = _run(tmp_path, "a_out_of_order")
    ups = _upserts(out)
    on_time = [(u.event.period, u.event.match_clock_ms) for u in ups if not u.late]
    assert on_time == sorted(on_time)
    assert pipe.stage.counts["late_inserts"] >= 1
    assert score(out, answer_key(fx.answer_key_dir)).recovery == 1.0


def test_duplicate_frame_batches_are_dropped(tmp_path):
    fx, out, pipe = _run(tmp_path, "b_duplicates")
    frames = [(o.batch.period, f.frame) for o in out if isinstance(o, FramesOut)
              for f in o.batch.frames]
    assert len(frames) == len(set(frames))
    assert len(frames) == sum(len(f.ball) for f in fx.truth.frames.values())
    assert pipe.stage.counts["frames_duplicate"] > 0


def test_conditions_and_stoppages_are_announced(tmp_path):
    _, out, _ = _run(tmp_path)
    kinds = Counter(o.kind for o in out if isinstance(o, Notice))
    assert kinds["conditions.changed"] == 2
    assert kinds["stoppage.start"] == 1 and kinds["stoppage.end"] == 1


def test_prematch_is_passed_on(tmp_path):
    _, out, _ = _run(tmp_path)
    assert out[0].kind == "prematch" and out[0].prematch["home"]["club_id"] == "RIV"


@pytest.mark.parametrize("cut", [0.3, 0.7])
def test_snapshot_round_trip_resumes_identically(tmp_path, cut):
    fx = generate(tmp_path, rules=frozenset({"a_duplicates", "a_out_of_order"}),
                  period_s=SHORT, halftime_s=60)
    msgs = list(messages(fx.feeds_dir))
    straight, _ = run(fx.feeds_dir, "fx01")

    pipe = Pipeline("fx01")
    out = []
    k = int(len(msgs) * cut)
    for m in msgs[:k]:
        out += pipe.process(m)
    resumed = Pipeline("fx01", stage=MergeStage.from_state(pipe.stage.to_state()),
                       teamsheet=pipe.teamsheet)
    for m in msgs[k:]:
        out += resumed.process(m)
    out += resumed.stage.flush(msgs[-1].wall_ms)
    assert [o.model_dump() for o in out] == [o.model_dump() for o in straight]


def test_snapshot_from_an_older_engine_still_loads(tmp_path):
    """Seen on Azure: a snapshot written before held_since existed made the new engine fail
    every message of that match after a restart."""
    fx = generate(tmp_path, rules=frozenset(), period_s=(60.0, 60.0), halftime_s=30)
    pipe = Pipeline("fx01")
    for m in list(messages(fx.feeds_dir))[:300]:
        pipe.process(m)
    old = pipe.stage.to_state()
    del old["held_since"]
    MergeStage.from_state(old)
