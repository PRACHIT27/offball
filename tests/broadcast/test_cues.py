"""Cue manager logic (Broadcast LLD §5–§9): versions, corrections, producer pulls, insights,
state for late joiners."""

from broadcast.cues import POSITIONS_KEEP, MatchCues, insight_cue_id


def cue(cue_id="cue-0001", version=1, status="on_air", reason=None, period=1, clock=600_000):
    return {"cue_id": cue_id, "version": version, "schema_version": "0.2", "match_id": "m1",
            "period": period, "kind": "pass_arc", "start_clock_ms": clock, "duration_ms": 2000,
            "anchor": None, "data": {"difficulty": 40}, "evidence": {"event_ids": ["e-000001"]},
            "captions": {}, "caption_source": "none", "status": status, "reason": reason}


def positions(period, clock):
    return {"kind": "positions", "match_id": "m1", "period": period, "match_clock_ms": clock,
            "values": {"frames": [{"frame": 1, "match_clock_ms": clock, "ball": [52, 34, 0],
                                   "players": {"RIV-07": [50.0, 30.0]}}],
                       "tags": {"RIV-07": {"speed_kmh": 20.0}}, "ball_speed_ms": 3.0}}


def test_newest_version_wins_and_older_is_ignored():
    m = MatchCues("m1")
    assert m.on_stats(cue(version=2), {"type": "cue"})
    assert m.on_stats(cue(version=1), {"type": "cue"}) == []
    assert m.cues["cue-0001"]["version"] == 2


def test_correction_withdraws_the_cue():
    m = MatchCues("m1")
    m.on_stats(cue(), {"type": "cue"})
    [env] = m.on_stats(cue(version=2, status="withdrawn", reason="correction"), {"type": "cue"})
    assert env["cue"]["status"] == "withdrawn" and env["cue"]["reason"] == "correction"
    assert m.counts["withdrawn"] == 1


def test_producer_pull_stays_off_air():
    m = MatchCues("m1")
    m.on_stats(cue(), {"type": "cue"})
    env = m.pull("cue-0001", "producer")
    assert env["cue"]["status"] == "withdrawn" and env["cue"]["reason"] == "producer_pull"
    assert env["cue"]["version"] == 2
    # A later metrics version (say a correction to the data) must not put it back on air
    assert m.on_stats(cue(version=3), {"type": "cue"}) == []
    assert m.cues["cue-0001"]["status"] == "withdrawn"
    assert m.pull("cue-0001") is None  # already pulled
    assert m.pull("cue-9999") is None
    assert [e["what"] for e in m.log] == ["cue", "pull"]


def test_insights_become_cues_once_and_can_be_pulled():
    m = MatchCues("m1")
    row = {"t": 4_300_000, "insight_id": "i-1", "trigger_id": "t-7", "kind": "expect",
           "captions": {"casual.en": "Expect a deeper line."}, "caption_source": "agent",
           "evidence": {"event_ids": ["e-000100"]}}
    assert len(m.add_insights([row])) == 1
    assert m.add_insights([row]) == []
    c = m.cues[insight_cue_id("i-1")]
    assert c["kind"] == "insight" and c["captions"]["casual.en"].startswith("Expect")
    assert m.pull(insight_cue_id("i-1"))["cue"]["status"] == "withdrawn"


def test_second_half_time_continues_after_first_half_stoppage():
    m = MatchCues("m1")
    m.on_stats(positions(1, 2_790_000), {"type": "stats"})  # 45+2'
    [env] = m.on_stats(positions(2, 2_700_000 + 60_000), {"type": "stats"})
    assert env["t"] == 2_790_000 + 60_000
    assert m.last_t == env["t"]


def test_state_has_recent_positions_cues_and_history():
    m = MatchCues("m1")
    for i in range(POSITIONS_KEEP + 10):
        m.on_stats(positions(1, i * 200), {"type": "stats"})
    m.on_stats(cue(), {"type": "cue"})
    m.on_stats({"kind": "shot", "match_id": "m1", "period": 1, "match_clock_ms": 900_000,
                "team_id": "RIV", "player_id": "RIV-09", "values": {"outcome": "goal"}},
               {"type": "stats"})
    m.on_stats({"kind": "series", "match_id": "m1", "team_id": "NGU", "period": 1,
                "at_ms": 900_000, "window_id": "w-1", "values": {"line_height_m": 33.0}}, {})
    m.on_stats({"kind": "note", "level": "tentative", "period": 1, "at_ms": 1}, {})
    m.on_stats({"kind": "heatmap", "period": 1, "match_clock_ms": 1}, {"type": "stats"})
    s = m.state()
    assert len(s["positions"]) == POSITIONS_KEEP
    assert len(s["cues"]) == 1 and len(s["stats"]) == 1 and len(s["tactics"]) == 1
    assert s["tactics"][0]["data"]["values"]["line_height_m"] == 33.0
    assert m.summary()["messages"] == POSITIONS_KEEP + 15


def test_pulled_insight_is_left_out_of_state_for_late_joiners():
    m = MatchCues("m1")
    m.add_insights([{"insight_id": "i-001", "t": 60_000, "kind": "shift", "captions": {},
                     "evidence": {}}, {"insight_id": "i-002", "t": 70_000, "kind": "summary",
                                       "captions": {}, "evidence": {}}])
    assert m.pull("ins-i-001")["cue"]["status"] == "withdrawn"
    assert [r["insight_id"] for r in m.state()["insights"]] == ["i-002"]
