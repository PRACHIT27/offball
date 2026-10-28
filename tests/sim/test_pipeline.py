"""Match control wakes the live pipeline on Play and puts it to sleep when idle: fakes, no Azure."""

import pytest
from fastapi.testclient import TestClient

from sim.control import app as control_app
from sim.control import runner as control_runner
from sim.control.pipeline import Pipeline
from sim.control.runner import Runner
from sim.control.senders import CountingSender
from tests.sim.test_control import wait_for

APPS = ["offball-engine", "offball-insights", "offball-cues"]


class FakeArm:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = dict(states)
        self.calls: list[tuple[str, str]] = []

    def status(self, app):
        return self.states[app]

    def start(self, app):
        self.calls.append(("start", app))
        self.states[app] = "Running"

    def stop(self, app):
        self.calls.append(("stop", app))
        self.states[app] = "Stopped"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def pipeline(states, healthy=lambda url: True, idle_minutes=20):
    clock = Clock()
    p = Pipeline(APPS, FakeArm(states), ["https://cues/health"], idle_minutes, healthy=healthy,
                 clock=clock, sleep=clock.sleep)
    return p, clock


def test_wake_starts_only_the_stopped_apps():
    p, _ = pipeline({"offball-engine": "Running", "offball-insights": "Stopped",
                     "offball-cues": "Stopped"})
    p.wake()
    assert p.arm.calls == [("start", "offball-insights"), ("start", "offball-cues")]
    assert p.state == "awake"


def test_wake_waits_for_health_then_gives_up_after_the_limit():
    p, clock = pipeline({a: "Stopped" for a in APPS}, healthy=lambda url: False)
    with pytest.raises(TimeoutError):
        p.wake()
    assert clock.now - 1_000.0 >= 180


def test_sleeps_after_idle_minutes_but_never_during_a_match():
    p, clock = pipeline({a: "Running" for a in APPS})
    p.wake()
    clock.now += 60 * 60  # an hour into a slow match
    assert not p.sleep_if_idle()
    p.match_over()
    clock.now += 19 * 60
    assert not p.sleep_if_idle()
    clock.now += 2 * 60
    assert p.sleep_if_idle()
    assert sorted(c for c in p.arm.calls if c[0] == "stop") == sorted(("stop", a) for a in APPS)
    assert p.state == "asleep"


def test_apps_left_running_at_boot_are_turned_off_too():
    p, clock = pipeline({a: "Running" for a in APPS})
    clock.now += 21 * 60
    assert p.sleep_if_idle()


@pytest.fixture
def client_with_pipeline(tmp_path, monkeypatch):
    from sim.output import generate
    from sim.storyline import load

    def short_prepare(storyline, seed, mess):
        import json
        out = tmp_path / f"{storyline}-{seed}-{mess}"
        if not (out / "match" / "match.json").exists():
            generate(load(storyline, seed), out, mess, period_s=(60.0, 60.0), halftime_s=5)
        return out / "feeds", json.loads((out / "match" / "match.json").read_text())

    monkeypatch.setattr(control_runner, "prepare", short_prepare)
    p, _ = pipeline({a: "Stopped" for a in APPS})
    sender = CountingSender()
    monkeypatch.setattr(control_app, "runner", Runner(sender_factory=lambda: sender, pipeline=p))
    monkeypatch.delenv("CONTROL_PASSCODE", raising=False)
    c = TestClient(control_app.app)
    c.pipeline = p
    return c


def test_play_wakes_the_pipeline_before_streaming(client_with_pipeline):
    c = client_with_pipeline
    assert c.post("/api/play", json={"storyline": "red_card", "speed": 10}).status_code == 200
    s = wait_for(c, {"streaming", "half-time", "finished"})
    assert s["pipeline"] == "awake"
    assert {a for op, a in c.pipeline.arm.calls if op == "start"} == set(APPS)
    c.post("/api/stop")
    assert not c.pipeline.playing
