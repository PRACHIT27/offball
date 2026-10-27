import copy
import json

import numpy as np
import pytest

from engine.tactics.config import TacticsConfig
from engine.tactics.local import run_tactics
from engine.tactics.measures import lines_formation
from engine.tactics.scoring import score
from engine.tactics.triggers import TriggerBuffer
from sim.output import generate
from sim.storyline import BUILT_IN


@pytest.fixture(scope="module")
def red_card(tmp_path_factory):
    m = generate(copy.deepcopy(BUILT_IN["red_card"]), tmp_path_factory.mktemp("rc"), "light")
    key = json.loads((m.answer_key_dir / "answer_key.json").read_text())
    return run_tactics(m.feeds_dir, m.truth.match_id), key


def _trigger(play_ms, team="NGU", reason="shift", type_="shift", tid="t-x"):
    return {"trigger_id": tid, "type": type_, "reason": reason, "team_id": team,
            "play_ms": play_ms, "importance": 0.6,
            "evidence": {"event_ids": [], "window_ids": [], "before": {}, "after": {}}}


def test_lines_formation_counts_lines():
    back = [10, 11, 10.5, 11.2]
    mid = [30, 31, 29.5, 30.4]
    front = [50, 51]
    assert lines_formation(np.array(back + mid + front)) == "4-4-2"
    assert lines_formation(np.array([10, 11, 10.5, 30, 31, 29, 30.5, 31.5, 50, 51])) == "3-5-2"


def test_config_rejects_unknown_settings(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"line_height_m": 5, "nope": 1}))
    with pytest.raises(ValueError):
        TacticsConfig.load(p)
    p.write_text(json.dumps({"line_height_m": 5}))
    assert TacticsConfig.load(p).line_height_m == 5


def test_buffer_caps_and_summarises():
    cfg = TacticsConfig()
    buf = TriggerBuffer(cfg)
    sent = []
    for i, t in enumerate([0, 70_000, 140_000, 210_000, 230_000]):
        sent += buf.offer(_trigger(t, tid=f"t-{i}"))
    assert [s["trigger_id"] for s in sent] == ["t-0", "t-1", "t-2"]
    assert not buf.due(300_000)
    due = buf.due(230_000 + 121_000)
    assert len(due) == 1 and [t["trigger_id"] for t in due[0][1].items] == ["t-3", "t-4"]


def test_goal_bypasses_cap_and_takes_held_triggers():
    buf = TriggerBuffer(TacticsConfig())
    for i, t in enumerate([0, 70_000, 140_000, 150_000]):
        buf.offer(_trigger(t, tid=f"t-{i}"))
    out = buf.offer(_trigger(160_000, reason="goal", type_="crux", tid="t-goal"))
    assert out and out[0]["merged_from"] == ["t-3"]
    assert "NGU" not in buf.holds


@pytest.mark.slow
def test_red_card_review_and_confirmation(red_card):
    results, _ = red_card
    trig = [r for r in results if r["sink"] == "triggers"]
    red = [t for t in trig if t["reason"] == "red_card"]
    assert len(red) == 1 and red[0]["team_id"] == "NGU"
    confirm = [t for t in trig if t["type"] == "confirm_due"
               and t["evidence"].get("crux_trigger_id") == red[0]["trigger_id"]]
    assert len(confirm) == 1
    ev = confirm[0]["evidence"]
    assert 3.5 <= (confirm[0]["play_ms"] - red[0]["play_ms"]) / 60000 <= 4.5
    assert ev["before"]["line_height_m"] - ev["after"]["line_height_m"] >= 5
    assert ev["did_it_work"] and "xg_against_per10" in ev["did_it_work"]["after"]


@pytest.mark.slow
def test_check_ins_windows_and_series(red_card):
    results, _ = red_card
    checks = [r for r in results if r.get("type") == "check_in"]
    assert [round(c["at_ms"] / 60000) for c in checks] == [15, 30, 45, 60, 75, 90]
    windows = [r for r in results if r.get("kind") == "window"]
    assert {w["team_id"] for w in windows} == {"RIV", "NGU"}
    assert any(r.get("kind") == "territory" for r in results)
    assert all("line_height_m" in r["values"] for r in results if r.get("kind") == "series")


@pytest.mark.slow
def test_detects_the_storyline_changes(red_card):
    results, key = red_card
    report = score(key, [r for r in results if r.get("kind") == "note"])
    found = {(m["team_id"], m["measure"], round(m["at_ms"] / 60000)) for m in report["matches"]}
    assert ("NGU", "line_height_m", 71) in found
    assert ("NGU", "formation_out", 46) in found
