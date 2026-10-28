"""Cue manager service (Broadcast LLD §7) on Container Apps: `stats` hub in, Web PubSub out.

- Reads the `stats` hub (consumer group `cues`): metrics positions, stats and number-only cues,
  and Tactical Intelligence's series, windows and notes.
- Polls Insight Generation (`INSIGHTS_URL`/api/insights) for checked captions; each becomes a cue.
- Pushes every change to Azure Web PubSub, hub `offball`, group `match-{id}`; browsers connect
  with a receive-only URL from `/api/negotiate`.
- `/api/matches`, `/api/matches/{id}/state` (late joiners), `/api/matches/{id}/cues` and
  `POST /api/cues/{id}/pull` (producer, needs PRODUCER_PASSCODE; refused when it is unset).
- `/producer`: the producer console. `/health`: counts.
- With FABRIC_KUSTO_URI set, the same messages and every producer pull also stream into the
  Fabric Eventhouse for the Real-Time Dashboard (broadcast/fabric.py).

Keyless: DefaultAzureCredential (the Container App's identity `id-cues`, AZURE_CLIENT_ID).

    python -m broadcast.service
"""

import asyncio
import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

from broadcast.cues import MatchCues
from broadcast.fabric import KustoSink
from broadcast.fabric import rows as fabric_rows

log = logging.getLogger("offball.cues")
HUB = "offball"
CONSOLE = Path(__file__).parent / "producer.html"
INSIGHTS_EVERY_S = 2.0
ALLOWED_ORIGINS = [o for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o]


def group(match_id: str) -> str:
    return f"match-{match_id}"


class CueService:
    def __init__(self, pubsub=None, cosmos=None, insights_url: str | None = None,
                 passcode: str | None = None, fabric=None) -> None:
        self.pubsub = pubsub
        # Optional broadcast.fabric.KustoSink: the same messages into the Fabric Eventhouse
        self.fabric = fabric
        self.cosmos = cosmos
        self.insights_url = insights_url.rstrip("/") if insights_url else None
        self.passcode = passcode
        self.matches: dict[str, MatchCues] = {}
        self.outbox: asyncio.Queue = asyncio.Queue(maxsize=5_000)
        self.started = time.time()
        self.counts = {"sent": 0, "dropped": 0, "send_errors": 0, "insights_polls": 0}
        self.insights_ok: bool | None = None

    def match(self, match_id: str) -> MatchCues:
        if match_id not in self.matches:
            self.matches[match_id] = MatchCues(match_id)
        return self.matches[match_id]

    # ---------- inputs ----------

    async def on_event(self, partition_context, event) -> None:
        if event is None:
            return
        props = {(k.decode() if isinstance(k, bytes) else k):
                 (v.decode() if isinstance(v, bytes) else v)
                 for k, v in (event.properties or {}).items()}
        try:
            body = json.loads(event.body_as_str())
        except ValueError:
            return
        match_id = body.get("match_id") or props.get("match_id")
        if not match_id:
            return
        m = self.match(match_id)
        if m.prematch is None and self.cosmos is not None:
            await self.load_prematch(m)
        self.publish(match_id, m.on_stats(body, props))
        if self.fabric is not None:
            at = props.get("emitted_at") or datetime.now(UTC).isoformat()
            self.fabric.extend(fabric_rows(at, body, props))

    async def load_prematch(self, m: MatchCues) -> None:
        try:
            doc = await self.cosmos.read_item("prematch", partition_key=m.match_id)
            m.prematch = doc.get("prematch")
        except Exception:  # not written yet: try again with the next message
            m.prematch = None

    async def poll_insights(self) -> None:
        """Every 2 s: new checked captions for each live match."""
        if not self.insights_url:
            return
        since: dict[str, float] = {}
        async with ClientSession(timeout=ClientTimeout(total=5)) as http:
            while True:
                await asyncio.sleep(INSIGHTS_EVERY_S)
                for match_id in list(self.matches):
                    try:
                        async with http.get(f"{self.insights_url}/api/insights",
                                            params={"match_id": match_id,
                                                    "since": since.get(match_id, 0)}) as r:
                            rows = (await r.json()).get("insights", []) if r.status == 200 else []
                        self.insights_ok = True
                    except Exception:
                        self.insights_ok = False
                        continue
                    self.counts["insights_polls"] += 1
                    if rows:
                        since[match_id] = max(row.get("received_at", 0) for row in rows)
                        self.publish(match_id, self.match(match_id).add_insights(rows))

    # ---------- output ----------

    def publish(self, match_id: str, envelopes: list[dict]) -> None:
        for env in envelopes:
            try:
                self.outbox.put_nowait((match_id, env))
            except asyncio.QueueFull:  # a slow Web PubSub never stalls the hub reader
                self.counts["dropped"] += 1

    async def sender(self) -> None:
        while True:
            match_id, env = await self.outbox.get()
            if self.pubsub is None:
                continue
            try:
                await self.pubsub.send_to_group(group(match_id), json.dumps(env),
                                                content_type="text/plain")
                self.counts["sent"] += 1
            except Exception:
                self.counts["send_errors"] += 1
                log.exception("Web PubSub send failed")

    # ---------- HTTP ----------

    def app(self) -> web.Application:
        app = web.Application(middlewares=[cors])
        app.add_routes([
            web.get("/health", self.health),
            web.get("/producer", self.console),
            web.get("/api/matches", self.list_matches),
            web.get("/api/matches/{match_id}/state", self.state),
            web.get("/api/matches/{match_id}/cues", self.list_cues),
            web.get("/api/negotiate", self.negotiate),
            web.post("/api/cues/{match_id}/{cue_id}/pull", self.pull),
        ])
        return app

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"up_s": round(time.time() - self.started), **self.counts,
                                  "outbox": self.outbox.qsize(), "insights_ok": self.insights_ok,
                                  "pubsub": self.pubsub is not None,
                                  "fabric": None if self.fabric is None else
                                  {"sent": self.fabric.sent, "failed": self.fabric.failed},
                                  "matches": [m.summary() for m in self.matches.values()]})

    async def console(self, request: web.Request) -> web.Response:
        return web.Response(text=CONSOLE.read_text(), content_type="text/html")

    async def list_matches(self, request: web.Request) -> web.Response:
        rows = sorted((m.summary() for m in self.matches.values()),
                      key=lambda s: -(s["last_message_at"] or 0))
        return web.json_response({"matches": rows, "now": time.time()})

    def _match(self, request: web.Request) -> MatchCues:
        match_id = request.match_info["match_id"]
        if match_id not in self.matches:
            raise web.HTTPNotFound(text="unknown match")
        return self.matches[match_id]

    async def state(self, request: web.Request) -> web.Response:
        return web.json_response(self._match(request).state())

    async def list_cues(self, request: web.Request) -> web.Response:
        m = self._match(request)
        cues = sorted(m.cues.values(), key=lambda c: -c["t"])[:300]
        # The summary's "cues" is a count; the list goes last so it isn't overwritten
        return web.json_response({**m.summary(), "cue_count": m.counts["cues"], "cues": cues,
                                  "log": list(m.log)[-200:]})

    async def negotiate(self, request: web.Request) -> web.Response:
        match_id = request.query.get("match", "")
        if match_id not in self.matches or self.pubsub is None:
            raise web.HTTPNotFound(text="no live push for that match")
        token = await self.pubsub.get_client_access_token(groups=[group(match_id)],
                                                         minutes_to_expire=120)
        return web.json_response({"url": token["url"]})

    async def pull(self, request: web.Request) -> web.Response:
        given = request.headers.get("X-Producer-Passcode", "")
        if not self.passcode or not hmac.compare_digest(given.encode(), self.passcode.encode()):
            raise web.HTTPUnauthorized(text="producer passcode required")
        m = self._match(request)
        who = request.headers.get("X-Producer", "producer")
        env = m.pull(request.match_info["cue_id"], who=who)
        if env is None:
            raise web.HTTPConflict(text="no such cue on air")
        self.publish(m.match_id, [env])
        if self.fabric is not None:
            self.fabric.extend(fabric_rows(datetime.now(UTC).isoformat(), env["cue"],
                                           {"type": "cue"}))
        log.info("producer pull %s %s", m.match_id, request.match_info["cue_id"])
        return web.json_response(env["cue"])


@web.middleware
async def cors(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)
    origin = request.headers.get("Origin")
    if origin and ("*" in ALLOWED_ORIGINS or origin in ALLOWED_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = ("Content-Type, X-Producer-Passcode, "
                                                        "X-Producer")
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


async def run() -> None:
    from azure.cosmos.aio import CosmosClient
    from azure.eventhub.aio import EventHubConsumerClient
    from azure.identity.aio import DefaultAzureCredential
    from azure.messaging.webpubsubservice.aio import WebPubSubServiceClient

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.setLevel(logging.INFO)
    async with DefaultAzureCredential() as cred:
        pubsub = WebPubSubServiceClient(os.environ["WEBPUBSUB_ENDPOINT"], hub=HUB, credential=cred)
        cosmos_client = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=cred) \
            if os.environ.get("COSMOS_ENDPOINT") else None
        cosmos = (cosmos_client.get_database_client("offball").get_container_client("events")
                  if cosmos_client else None)
        http = ClientSession(timeout=ClientTimeout(total=30))
        fabric = KustoSink(os.environ["FABRIC_KUSTO_URI"], cred, http) \
            if os.environ.get("FABRIC_KUSTO_URI") else None
        svc = CueService(pubsub, cosmos, os.environ.get("INSIGHTS_URL"),
                         os.environ.get("PRODUCER_PASSCODE") or None, fabric)
        hub = EventHubConsumerClient(os.environ["EVENTHUB_NAMESPACE"], "cues",
                                     eventhub_name="stats", credential=cred)
        runner = web.AppRunner(svc.app())
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", "8080"))).start()
        log.info("cue manager up: stats (group cues) -> Web PubSub hub %s", HUB)
        tasks = [asyncio.create_task(svc.sender()), asyncio.create_task(svc.poll_insights())]
        if fabric:
            tasks.append(asyncio.create_task(fabric.run()))
        try:
            async with hub:
                # Only from now: a restart rebuilds live matches from new messages
                await hub.receive(svc.on_event, starting_position="@latest")
        finally:
            for task in tasks:
                task.cancel()
            await pubsub.close()
            await http.close()
            if cosmos_client:
                await cosmos_client.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
