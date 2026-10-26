"""Performance Metrics on the Azure path without Azure: NormalizerService → in-memory hub →
EngineCore(router=MetricsRouter) → fake `stats` hub and Cosmos `metrics`. Must match local mode,
including across an engine restart from snapshots."""

import json

import numpy as np
import pytest

from engine.core import EngineCore
from engine.local import messages
from engine.merge.stage import parse_wall
from engine.metrics.local import run_metrics
from engine.metrics.publisher import Publisher
from engine.metrics.service import MetricsRouter
from engine.metrics.sinks_azure import CosmosMetricsSink, StatsHubSink
from engine.store_local import LocalStore
from ingest.service import NormalizerService
from tests.engine.test_azure_path import Memory
from tests.fixturegen.generate import generate


class FakeEventData:
    def __init__(self, body: str) -> None:
        self.body = body
        self.properties: dict = {}


class FakeBatch(list):
    def __init__(self, partition_key: str, limit: int = 50) -> None:
        super().__init__()
        self.partition_key = partition_key
        self.limit = limit

    def add(self, data) -> None:
        if len(self) >= self.limit:
            raise ValueError("batch full")
        self.append(data)


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[FakeBatch] = []

    def create_batch(self, partition_key: str) -> FakeBatch:
        return FakeBatch(partition_key)

    def send_batch(self, batch: FakeBatch) -> None:
        self.sent.append(batch)

    def messages(self) -> list[tuple[dict, dict]]:
        return [(json.loads(d.body), d.properties) for b in self.sent for d in b]


class FakeContainer:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def upsert_item(self, item: dict) -> None:
        self.items[item["id"]] = item


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("fx"), mess_level="full", period_s=(240.0, 240.0),
                    halftime_s=60)


@pytest.fixture(scope="module")
def hub(fx):
    out = []
    service = NormalizerService(Memory(), Memory(), out.extend,
                                now=lambda: "2026-10-25T14:00:00.000Z")
    for m in messages(fx.feeds_dir):
        service.handle_batch(m.feed, [(m.body, m.properties)])
    return out


def run_azure(hub, root, crash_at=None):
    producer, cosmos, snapshots = FakeProducer(), FakeContainer(), Memory()

    def fresh():
        router = MetricsRouter(
            Publisher([StatsHubSink(producer, FakeEventData, now=lambda: "t"),
                       CosmosMetricsSink(cosmos)]), snapshots)
        return EngineCore(lambda m: LocalStore(root, m), snapshots, router), router

    core, router = fresh()
    for i, (body, headers, _) in enumerate(hub):
        if crash_at is not None and i == int(len(hub) * crash_at):
            core.checkpoint()
            router.checkpoint()
            core, router = fresh()
        core.handle(body, headers, parse_wall(headers["emitted_at"]))
    end = parse_wall(hub[-1][1]["emitted_at"])
    core.tick(end + 10_000, wall_ms=end)
    core.checkpoint()
    router.checkpoint()
    return producer, cosmos, router


def latest_results(stats: list[dict]) -> dict:
    """Final pass and shot result per event, as a consumer keeping the highest version sees it."""
    out = {}
    for s in stats:
        if s["kind"] in ("pass", "shot"):
            key = s["evidence"]["event_ids"][0]
            if key not in out or s["version"] >= out[key]["version"]:
                out[key] = s
    return {k: (v["status"], v["values"]) for k, v in out.items()}


@pytest.fixture(scope="module")
def local(fx, tmp_path_factory):
    out = tmp_path_factory.mktemp("local")
    e, _ = run_metrics(fx.feeds_dir, out, "fx01")
    stats = [json.loads(line) for line in (out / "metrics/fx01/stats.jsonl").open()]
    return e, stats


@pytest.mark.parametrize("crash_at", [None, 0.5])
def test_azure_path_matches_local_mode(hub, local, tmp_path, crash_at):
    local_engine, local_stats = local
    producer, cosmos, router = run_azure(hub, tmp_path, crash_at)
    stats = [body for body, props in producer.messages() if props["type"] == "stats"]
    ours, theirs = latest_results(stats), latest_results(local_stats)
    assert ours.keys() == theirs.keys()
    differ = [k for k in ours if ours[k] != theirs[k]]
    # The 10 s frame memory isn't snapshotted: an event waiting for frames at the restart is
    # computed from the frames after it only
    assert len(differ) <= (0 if crash_at is None else 2), differ
    a, b = local_engine.totals, router.engines["fx01"].totals
    for name in ("passes", "passes_completed", "shots", "sprints"):
        assert getattr(a, name).tolist() == getattr(b, name).tolist(), name
    assert np.allclose(a.distance, b.distance, rtol=0.005, atol=1.0)
    assert any(k.startswith("player:") for k in cosmos.items)
    assert any(k.startswith("event:") for k in cosmos.items)
    assert all(d["match_id"] == "fx01" and d["doc_type"] for d in cosmos.items.values())


def test_stats_hub_messages_carry_type_kind_and_partition_key(hub, tmp_path):
    producer, _, _ = run_azure(hub, tmp_path)
    assert {b.partition_key for b in producer.sent} == {"fx01"}
    assert all(len(b) <= 50 for b in producer.sent)
    msgs = producer.messages()
    cues = [(body, p) for body, p in msgs if p["type"] == "cue"]
    assert cues and all(body["cue_id"].startswith("cue-") and p["kind"] == body["kind"]
                        for body, p in cues)
    assert {p["type"] for _, p in msgs} == {"stats", "cue"}
    assert all({"match_id", "emitted_at"} <= p.keys() for _, p in msgs)
