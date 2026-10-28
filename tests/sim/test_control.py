import time

import pytest
from fastapi.testclient import TestClient

from sim.control import app as control_app
from sim.control import runner as control_runner
from sim.control.runner import Runner
from sim.control.senders import CountingSender
from sim.output import generate
from sim.storyline import load


@pytest.fixture
def client(tmp_path, monkeypatch):
    def short_prepare(storyline, seed, mess):
        out = tmp_path / f"{storyline}-{seed}-{mess}"
        if not (out / "match" / "match.json").exists():
            generate(load(storyline, seed), out, mess, period_s=(120.0, 120.0), halftime_s=30)
        import json
        return out / "feeds", json.loads((out / "match" / "match.json").read_text())

    monkeypatch.setattr(control_runner, "prepare", short_prepare)
    sender = CountingSender()
    monkeypatch.setattr(control_app, "runner", Runner(sender_factory=lambda: sender))
    monkeypatch.delenv("CONTROL_PASSCODE", raising=False)
    c = TestClient(control_app.app)
    c.sender = sender
    return c


def wait_for(client, phases, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get("/api/status").json()
        if s["phase"] in phases:
            return s
        time.sleep(0.2)
    raise AssertionError(f"still {s['phase']}")


def test_page_and_storylines(client):
    assert "Match control" in client.get("/").text
    names = [s["name"] for s in client.get("/api/storylines").json()["storylines"]]
    assert "red_card" in names and "random" in names


def test_play_streams_every_message_once(client):
    r = client.post("/api/play", json={"storyline": "red_card", "speed": 10, "mess": "light"})
    assert r.status_code == 200
    assert client.post("/api/play", json={"storyline": "storm"}).status_code == 409
    s = wait_for(client, {"finished", "error"})
    assert s["phase"] == "finished", s["message"]
    assert s["sent"]["A"] + s["sent"]["B"] == s["total"]
    assert client.sender.sent == s["sent"]
    assert s["match_id"].startswith("m001-") and s["minute"] > 45


def test_stop_ends_the_run(client):
    client.post("/api/play", json={"storyline": "random", "seed": 4, "speed": 1, "mess": "off"})
    wait_for(client, {"streaming"})
    s = client.post("/api/stop").json()
    assert s["phase"] == "stopped"


def test_bad_requests_are_rejected(client, monkeypatch):
    assert client.post("/api/play", json={"storyline": "nope"}).status_code == 400
    assert client.post("/api/play", json={"storyline": "red_card", "speed": 30}).status_code == 400
    monkeypatch.setenv("CONTROL_PASSCODE", "pitch")
    assert client.post("/api/play", json={"storyline": "red_card"}).status_code == 401


def test_each_play_gets_its_own_match_id(tmp_path):
    generate(load("red_card", None), tmp_path, "light", period_s=(60.0, 60.0), halftime_s=10)
    live = control_runner.run_id("m001")
    schedule = control_runner.plan(tmp_path / "feeds", 10, ("m001", live))
    assert schedule and all(props["match_id"] == live for _, _, _, props in schedule)
    assert all('"m001"' not in body for _, _, body, _ in schedule)
    assert sum(f'"{live}"' in body for _, _, body, _ in schedule) == len(schedule)


def test_status_links_to_the_viewer_when_configured(client, monkeypatch):
    assert client.get("/api/status").json()["viewer_url"] is None
    monkeypatch.setenv("VIEWER_URL", "https://viewer.example/")
    assert client.get("/api/status").json()["viewer_url"] == "https://viewer.example"
