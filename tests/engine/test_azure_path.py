"""The Azure path without Azure: NormalizerService → in-memory hub → EngineCore → store must give
the same Silver as local mode, including across an engine restart from a snapshot."""

import json

import pytest

from engine.core import EngineCore
from engine.local import messages, run_local
from engine.merge.stage import parse_wall
from engine.store_local import LocalStore
from ingest.service import NormalizerService
from tests.fixturegen.generate import generate


class Memory:
    def __init__(self):
        self.data = {}

    def load(self, key):
        return self.data.get(key)

    def save(self, key, value):
        self.data[key] = value

    def write(self, path, record):
        self.data[path] = record


def _silver(root):
    s = LocalStore(root, "fx01")
    return {"events": s.events, "notices": s.notices, "prematch": s.prematch,
            "frames": s.read_frames()}


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("fx"), mess_level="full", period_s=(240.0, 240.0),
                    halftime_s=60)


@pytest.fixture(scope="module")
def normalized(fx):
    """Everything the two Functions would publish to `normalized`, in arrival order."""
    hub, dead = [], Memory()
    sheets = Memory()
    service = NormalizerService(sheets, dead, hub.extend, now=lambda: "2026-10-25T14:00:00.000Z")
    for m in messages(fx.feeds_dir):
        # One message per trigger batch keeps arrival order identical to local mode
        service.handle_batch(m.feed, [(m.body, m.properties)])
    return hub, dead, sheets


def test_service_publishes_with_match_partition_key_and_headers(normalized):
    hub, _, sheets = normalized
    assert {key for _, _, key in hub} == {"fx01"}
    assert {h["kind"] for _, h, _ in hub} == {"prematch", "event", "delete", "frames"}
    assert json.loads(sheets.data["fx01"])["home"]["provider_team_id"] == 101


def test_broken_records_go_to_dead_letter_paths(normalized, fx):
    _, dead, _ = normalized
    assert len(dead.data) == len(fx.mess_log["a_broken"])
    for path, record in dead.data.items():
        match_id, stage, _ = path.split("/")
        assert match_id == "fx01" and stage == record["stage"]


def _run_engine(hub, root, crash_at=None):
    snapshots = Memory()

    def fresh():
        return EngineCore(lambda m: LocalStore(root, m), snapshots)

    core = fresh()
    restarted = False
    for i, (body, headers, _) in enumerate(hub):
        if crash_at is not None and i == int(len(hub) * crash_at):
            core.checkpoint()
            core = fresh()  # engine restarts from the snapshot
            restarted = True
        core.handle(body, headers, parse_wall(headers["emitted_at"]))
    end = parse_wall(hub[-1][1]["emitted_at"])
    core.tick(end + 10_000, wall_ms=end)
    core.checkpoint()
    assert restarted == (crash_at is not None)


@pytest.mark.parametrize("crash_at", [None, 0.5])
def test_engine_core_gives_the_same_silver_as_local_mode(fx, normalized, tmp_path, crash_at):
    run_local(fx.feeds_dir, tmp_path / "local", "fx01")
    _run_engine(normalized[0], tmp_path / "azure", crash_at)
    local, azure = _silver(tmp_path / "local"), _silver(tmp_path / "azure")
    strip = lambda evs: {k: {**v, "timings": {}} for k, v in evs.items()}  # noqa: E731
    assert strip(azure["events"]) == strip(local["events"])
    assert azure["notices"].keys() == local["notices"].keys()
    assert azure["frames"] == local["frames"]
    assert azure["prematch"] == local["prematch"]
