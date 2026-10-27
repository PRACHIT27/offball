import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

import insights.agents
import insights.service as service
import insights.workflow
from insights.local import template_insight


class FakeCosmos:
    def __init__(self, data):
        self.data = data

    async def read_item(self, item, partition_key):
        return {"prematch": self.data.prematch}

    async def query_items(self, query, parameters, partition_key):
        for e in self.data.events.values():
            if e["type"] in parameters[0]["value"]:
                yield {**e, "id": f"{e['event_id']}:1", "doc_type": "event"}


class FakeTeam:
    def __init__(self, *a):
        pass

    async def __aenter__(self):
        return self


class Event:
    def __init__(self, body):
        self.body = json.dumps(body)

    def body_as_str(self):
        return self.body


def test_trigger_to_insight_over_http(data, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(service, "SETTLE_S", 0)
    monkeypatch.setattr(insights.agents, "Team", FakeTeam)
    calls = []

    async def fake_run(trigger, d, team):
        calls.append(trigger["trigger_id"])
        return template_insight(trigger, d)

    monkeypatch.setattr(insights.workflow, "run_trigger", fake_run)
    trigger = {**data.triggers[1], "match_id": "m1"}  # the red card

    async def scenario():
        svc = service.InsightService(None, FakeCosmos(data), "ns")
        await svc.on_trigger(None, Event(trigger))
        await svc.on_trigger(None, Event(trigger))  # delivered twice
        await asyncio.sleep(0.2)
        async with TestClient(TestServer(svc.app())) as client:
            matches = await (await client.get("/api/matches")).json()
            rows = (await (await client.get("/api/insights?match_id=m1")).json())["insights"]
            later = (await (await client.get(
                f"/api/insights?match_id=m1&since={rows[0]['received_at']}")).json())["insights"]
            page = await (await client.get("/")).text()
        return matches, rows, later, page

    matches, rows, later, page = asyncio.run(scenario())
    assert calls == ["t-002"]  # one insight per trigger (IG-2)
    assert matches[0]["home"] == "Riverside Athletic" and matches[0]["insights"] == 1
    assert rows[0]["kind"] == "expect" and "Red card" in rows[0]["captions"]["casual.en"]
    assert later == []
    assert "OffBall Live Captions" in page
    assert (tmp_path / "m1" / "insights" / "data" / "triggers.jsonl").exists()
