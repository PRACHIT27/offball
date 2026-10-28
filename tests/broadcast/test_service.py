"""Cue manager service with fakes for Event Hubs and Web PubSub: no Azure."""

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from broadcast.service import CueService, group
from tests.broadcast.test_cues import cue, positions


class FakeEvent:
    def __init__(self, body: dict, props: dict) -> None:
        self._body = json.dumps(body)
        self.properties = {k.encode(): v.encode() for k, v in props.items()}

    def body_as_str(self) -> str:
        return self._body


class FakePubSub:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_to_group(self, group_name, message, content_type=None):
        self.sent.append((group_name, json.loads(message)))

    async def get_client_access_token(self, groups=None, minutes_to_expire=60):
        return {"url": f"wss://example.webpubsub.azure.com/client/hubs/offball?groups={groups[0]}"}


def run(coro):
    return asyncio.run(coro)


async def _with_client(svc, fn):
    client = TestClient(TestServer(svc.app()))
    await client.start_server()
    try:
        return await fn(client)
    finally:
        await client.close()


def test_hub_messages_reach_web_pubsub_group():
    async def go():
        pubsub = FakePubSub()
        svc = CueService(pubsub)
        sender = asyncio.create_task(svc.sender())
        await svc.on_event(None, FakeEvent(positions(1, 1000), {"type": "stats", "match_id": "m1"}))
        await svc.on_event(None, FakeEvent(cue(), {"type": "cue", "match_id": "m1"}))
        await asyncio.sleep(0.05)
        sender.cancel()
        return pubsub.sent
    sent = run(go())
    assert [g for g, _ in sent] == [group("m1")] * 2
    assert [e["type"] for _, e in sent] == ["positions", "cue"]


def test_pull_needs_the_passcode_and_withdraws_for_everyone():
    async def go():
        svc = CueService(FakePubSub(), passcode="s3cret")
        await svc.on_event(None, FakeEvent(cue(), {"type": "cue", "match_id": "m1"}))

        async def calls(client):
            url = "/api/cues/m1/cue-0001/pull"
            no = await client.post(url)
            wrong = await client.post(url, headers={"X-Producer-Passcode": "nope"})
            ok = await client.post(url, headers={"X-Producer-Passcode": "s3cret"})
            again = await client.post(url, headers={"X-Producer-Passcode": "s3cret"})
            return no.status, wrong.status, ok.status, (await ok.json())["reason"], again.status
        return await _with_client(svc, calls), svc.outbox.qsize()
    (no, wrong, ok, reason, again), queued = run(go())
    assert (no, wrong, ok, again) == (401, 401, 200, 409)
    assert reason == "producer_pull" and queued == 2  # the cue, then its withdrawal


def test_pull_is_refused_when_no_passcode_is_configured():
    async def go():
        svc = CueService(FakePubSub(), passcode=None)
        await svc.on_event(None, FakeEvent(cue(), {"type": "cue", "match_id": "m1"}))
        return await _with_client(svc, lambda c: c.post("/api/cues/m1/cue-0001/pull",
                                                         headers={"X-Producer-Passcode": ""}))
    assert run(go()).status == 401


def test_state_matches_and_negotiate():
    async def go():
        svc = CueService(FakePubSub())
        await svc.on_event(None, FakeEvent(positions(1, 1000), {"type": "stats", "match_id": "m1"}))

        async def calls(client):
            matches = await (await client.get("/api/matches")).json()
            state = await (await client.get("/api/matches/m1/state")).json()
            neg = await (await client.get("/api/negotiate?match=m1")).json()
            missing = await client.get("/api/matches/zzz/state")
            return matches, state, neg, missing.status
        return await _with_client(svc, calls)
    matches, state, neg, missing = run(go())
    assert [m["match_id"] for m in matches["matches"]] == ["m1"]
    assert len(state["positions"]) == 1 and state["positions"][0]["t"] == 1000
    assert neg["url"].startswith("wss://") and missing == 404


def test_cue_list_for_the_console_is_a_list():
    async def go():
        svc = CueService(FakePubSub())
        await svc.on_event(None, FakeEvent(cue(), {"type": "cue", "match_id": "m1"}))

        async def call(client):
            return await (await client.get("/api/matches/m1/cues")).json()
        return await _with_client(svc, call)
    data = run(go())
    assert isinstance(data["cues"], list) and data["cues"][0]["cue_id"] == "cue-0001"
    assert data["cue_count"] == 1
