"""Ingestion LLD §11: restart, idempotent replay, local mode, recovery score at `light`."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.local import checkpoint_path, run_local
from engine.store_local import LocalStore
from tests.evaluate import answer_key, score_store
from tests.fixturegen.generate import generate

REPO = Path(__file__).resolve().parents[2]
SHORT = (240.0, 240.0)


def _silver(out: Path, match_id: str = "fx01") -> dict:
    s = LocalStore(out, match_id)
    return {"events": s.events, "notices": s.notices, "dead": s.dead_letters,
            "prematch": s.prematch, "frames": s.read_frames()}


@pytest.fixture(scope="module")
def light(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("light"), mess_level="light", period_s=SHORT,
                    halftime_s=60)


@pytest.fixture(scope="module")
def straight(light, tmp_path_factory):
    out = tmp_path_factory.mktemp("straight")
    run_local(light.feeds_dir, out, "fx01", checkpoint_every=500)
    return _silver(out)


@pytest.mark.parametrize("kills", [[0.45], [0.2, 0.6, 0.9]])
def test_restart_loses_and_doubles_nothing(light, straight, tmp_path, kills):
    total = sum(1 for _ in (light.feeds_dir / "feed_a.jsonl").open()) + sum(
        1 for _ in (light.feeds_dir / "feed_b.jsonl").open())
    for share in kills:
        r = run_local(light.feeds_dir, tmp_path, "fx01", checkpoint_every=500,
                      stop_after=int(total * share))
        assert not r.finished
    assert run_local(light.feeds_dir, tmp_path, "fx01", checkpoint_every=500).finished
    assert _silver(tmp_path) == straight


def test_replaying_the_whole_feed_twice_changes_nothing(light, straight, tmp_path):
    run_local(light.feeds_dir, tmp_path, "fx01", checkpoint_every=500)
    ck = checkpoint_path(tmp_path, "fx01")
    state = json.loads(ck.read_text())
    state["position"] = 0  # deliver every message again, keeping the engine's memory
    ck.write_text(json.dumps(state))
    run_local(light.feeds_dir, tmp_path, "fx01", checkpoint_every=500)
    assert _silver(tmp_path) == straight


def test_recovery_at_light_mess(light, tmp_path):
    r = run_local(light.feeds_dir, tmp_path, "fx01")
    assert score_store(r.store, answer_key(light.answer_key_dir)).recovery >= 0.99
    assert abs(r.counts["clock_offset_ms"] - light.clock_offset_ms) <= 80


def test_live_code_never_reads_the_answer_key():
    for package in ("ingest", "engine", "insights"):
        for path in (REPO / package).rglob("*.py"):
            text = path.read_text().lower()
            assert "answer" not in text and "tests." not in text, path


@pytest.mark.slow
def test_full_match_in_local_mode_without_azure(tmp_path):
    """Full 90-minute match, `light` mess, through the CLI with no Azure settings at all."""
    fx = generate(tmp_path / "fx", mess_level="light")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    code = ("import sys, runpy; sys.argv=['engine.local','--feeds',sys.argv[1],'--out',"
            "sys.argv[2],'--match','fx01']; runpy.run_module('engine.local', run_name='__main__');"
            "assert not [m for m in sys.modules if m.startswith('azure')]")
    done = subprocess.run([sys.executable, "-c", code, str(fx.feeds_dir), str(tmp_path / "out")],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr
    store = LocalStore(tmp_path / "out", "fx01")
    s = score_store(store, answer_key(fx.answer_key_dir))
    assert s.recovery >= 0.99, (s.recovery, s.missing[:10])
    counts = json.loads((tmp_path / "out/silver/fx01/counts.json").read_text())
    assert abs(counts["clock_offset_ms"] - fx.clock_offset_ms) <= 80
    assert len(store.read_frames()) >= sum(len(f.ball) for f in fx.truth.frames.values()) - 50
