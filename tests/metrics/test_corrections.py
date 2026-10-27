"""Correction handler (PM-25, LLD §9): corrections recompute, update totals, withdraw cues."""

from engine.metrics.models import Cue, StatsMessage
from engine.metrics.router import MetricsEngine
from tests.metrics.scenes import batches, delete, engine, frame, run, upsert
from tests.metrics.test_events import PLAYERS, a_pass, of, pass_frames


def computed() -> MetricsEngine:
    e = engine()
    run(e, batches(pass_frames()))
    e.dispatch(upsert(a_pass()))
    return e


def test_pass_corrected_to_intercepted_withdraws_its_cue_and_lowers_accuracy():
    e = computed()
    c = e.roster.col["RIV-07"]
    out = e.dispatch(upsert(a_pass(version=2, outcome="incomplete")))
    [arc] = of(out, Cue, "pass_arc")
    assert arc.status == "withdrawn" and arc.reason == "correction" and arc.version == 2
    [msg] = of(out, StatsMessage, "pass")
    assert msg.version == 2 and msg.values["completed"] is False
    assert (e.totals.passes[c], e.totals.passes_completed[c]) == (1, 0)


def test_older_version_is_ignored():
    e = computed()
    e.dispatch(upsert(a_pass(version=3, outcome="incomplete")))
    assert e.dispatch(upsert(a_pass(version=2))) == []


def test_deleted_pass_is_removed_everywhere():
    e = computed()
    c = e.roster.col["RIV-07"]
    out = e.dispatch(delete(a_pass()))
    assert [cue.status for cue in of(out, Cue)] == ["withdrawn"]
    [msg] = of(out, StatsMessage, "pass")
    assert msg.status == "deleted"
    assert (e.totals.passes[c], e.totals.passes_completed[c]) == (0, 0)
    assert e.totals.expected_completed[c] == 0.0


def test_correction_after_frames_left_memory_keeps_frame_values():
    e = computed()
    # 15 s more play: the pass's frames are out of the 10 s memory
    run(e, batches([frame(n, PLAYERS, ball=(70.0, 34.0, 0.0)) for n in range(200, 575)]))
    assert e.memory.nearest_index(1, 4000) is None
    out = e.dispatch(upsert(a_pass(version=2, outcome="complete", target="RIV-09")
                            .model_copy(update={"end": a_pass().end.model_copy(
                                update={"x": 69.0})})))
    [msg] = of(out, StatsMessage, "pass")
    assert msg.values["speed_ms"] is not None and msg.values["pressure_passer"] > 0
    assert msg.values["distance_m"] == 18.6
    [arc] = of(out, Cue, "pass_arc")
    assert arc.version == 2 and arc.status == "on_air" and arc.data["end"] == [69.0, 34.0]


def test_deleted_shot_shrinks_the_xg_summary():
    from tests.metrics.scenes import event

    e = engine()
    run(e, batches(pass_frames()))
    shots = [event(f"e-00040{i}", "shot", 100, "RIV-09", start=(90, 34), end=(105, 34),
                   outcome="saved", provider_xg=x) for i, x in enumerate([0.4, 0.1])]
    for s in shots:
        e.dispatch(upsert(s))
    out = e.dispatch(delete(shots[0]))
    [xg] = of(out, StatsMessage, "xg")
    assert xg.values["shots"] == 1 and xg.values["big_chances"] == 0
    summary = [c for c in of(out, Cue, "xg_summary")][-1]
    assert summary.status == "on_air" and summary.data["shots"] == 1
    out = e.dispatch(delete(shots[1]))
    assert [c.status for c in of(out, Cue, "xg_summary")] == ["withdrawn"]
