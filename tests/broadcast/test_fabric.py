"""Fabric rows from hub messages, and the cue manager's optional Fabric sink: no Azure."""

import asyncio

from broadcast.fabric import KustoSink, rows
from broadcast.service import CueService
from tests.broadcast.test_cues import cue, positions
from tests.broadcast.test_service import FakeEvent

AT = "2026-10-27T19:00:00+00:00"


def test_cue_becomes_a_cues_row():
    [(table, row)] = rows(AT, cue(), {"type": "cue"})
    assert table == "Cues"
    assert row["cue_id"] == cue()["cue_id"] and row["status"] == "on_air"
    assert row["minute"] == round(cue()["start_clock_ms"] / 60_000, 3)


def test_positions_keep_ball_speed_but_not_frames():
    [(table, row)] = rows(AT, positions(1, 1000), {"type": "stats"})
    assert table == "Stats" and row["message"] == "positions"
    assert "frames" not in row["data"] and "tags" not in row["data"]


def test_tactics_series_and_triggers():
    series = {"sink": "stats", "kind": "series", "match_id": "m1", "team_id": "RIV",
              "period": 2, "at_ms": 3_000_000, "window_id": "w-RIV-2-4950-5000",
              "values": {"line_height_m": 41.2}}
    [(table, row)] = rows(AT, series, {})
    assert (table, row["clock_ms"], row["minute"]) == ("Stats", 3_000_000, 50.0)
    assert row["data"] == {"line_height_m": 41.2}
    trig = {"sink": "triggers", "trigger_id": "t-001", "match_id": "m1", "type": "crux",
            "reason": "goal", "team_id": "NGU", "importance": 1.0, "at_ms": 60_000,
            "period": 1, "evidence": {"event_ids": ["e-000001"]}}
    [(table, row)] = rows(AT, trig, {})
    assert table == "Triggers" and row["evidence"]["event_ids"] == ["e-000001"]


def test_window_drops_network_and_positions():
    win = {"sink": "stats", "kind": "window", "window_id": "w-RIV-1-0000-0010",
           "match_id": "m1", "team_id": "RIV", "period": 1, "from_ms": 0, "to_ms": 10_000,
           "values": {"chaos": 75.3}, "network": {"a": 1}, "routes": [], "positions": {},
           "unusual": False}
    [(_, row)] = rows(AT, win, {})
    assert row["data"] == {"chaos": 75.3, "unusual": False, "window_id": "w-RIV-1-0000-0010"}
    assert row["clock_ms"] == 10_000


def test_cue_manager_copies_messages_to_fabric_without_sending():
    async def go():
        sink = KustoSink("https://example.kusto.fabric.microsoft.com", None, None)
        svc = CueService(fabric=sink)
        await svc.on_event(None, FakeEvent(cue(), {"type": "cue", "match_id": "m1",
                                                   "emitted_at": AT}))
        return sink.buffers
    buffers = asyncio.run(go())
    assert list(buffers) == ["Cues"] and AT in buffers["Cues"][0]
