"""Live Insight Generation (LLD §2, §9): triggers in, checked captions out, while the match plays.

- Tactical Intelligence's windows and notes arrive on the `stats` hub (consumer group `insights`)
  and its triggers on `triggers` (consumer group `agents`).
- Pre-match info and the key events (goals, cards, subs, conditions) come from Cosmos `events`.
- Each trigger runs the agent workflow once (IG-2); the MCP stats server reads a per-match
  snapshot of the data that the service rewrites before every run.
- Captions are served over HTTP: `/api/insights?match_id=…&since=…` and a live page at `/`.

Runs as Container App `offball-insights` with identity `id-insights`; keyless everywhere.
"""

import asyncio
import json
import logging
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import web

from insights.data import MatchData

log = logging.getLogger("offball.insights")
DATA_ROOT = Path(os.environ.get("INSIGHTS_DATA_ROOT", "/tmp/offball-insights"))
STATS_LOOKBACK = timedelta(hours=float(os.environ.get("STATS_LOOKBACK_HOURS", "3")))
KEY_EVENT_TYPES = ("shot", "card", "sub_on", "sub_off", "conditions", "stoppage_start")
# Windows published with a trigger can arrive just after it on the other hub
SETTLE_S = 2.0
CONCURRENCY = int(os.environ.get("INSIGHTS_CONCURRENCY", "2"))
LIVE_PAGE = Path(__file__).parent / "live.html"


class LiveMatch:
    def __init__(self, match_id: str):
        self.data = MatchData(match_id)
        self.dir = DATA_ROOT / match_id / "insights" / "data"
        self.team = None
        self.seen: set[str] = set()
        self.insights: list[dict] = []
        self.lock = asyncio.Lock()


class InsightService:
    def __init__(self, credential, cosmos_container, namespace: str):
        self.credential = credential
        self.cosmos = cosmos_container
        self.namespace = namespace
        self.matches: dict[str, LiveMatch] = {}
        self.gate = asyncio.Semaphore(CONCURRENCY)
        self.started = time.time()
        self.counts = {"windows": 0, "triggers": 0, "insights": 0, "errors": 0}
        self.last_error: str | None = None

    def match(self, match_id: str) -> LiveMatch:
        if match_id not in self.matches:
            self.matches[match_id] = LiveMatch(match_id)
        return self.matches[match_id]

    # ---------- inputs ----------

    async def on_stats(self, partition_context, event) -> None:
        if event is None:
            return
        try:
            r = json.loads(event.body_as_str())
        except ValueError:
            return
        if r.get("kind") in ("window", "note") and r.get("match_id"):
            self.match(r["match_id"]).data.add_tactics(r)
            self.counts["windows"] += r["kind"] == "window"

    async def on_trigger(self, partition_context, event) -> None:
        if event is None:
            return
        try:
            trigger = json.loads(event.body_as_str())
        except ValueError:
            return
        m = self.match(trigger["match_id"])
        if trigger["trigger_id"] in m.seen:  # delivered twice: one insight (IG-2)
            return
        m.seen.add(trigger["trigger_id"])
        self.counts["triggers"] += 1
        asyncio.create_task(self.explain(m, trigger))

    async def refresh_events(self, m: LiveMatch) -> None:
        if not m.data.prematch:
            doc = await self.cosmos.read_item("prematch", partition_key=m.data.match_id)
            m.data.prematch = doc["prematch"]
        query = ("SELECT * FROM c WHERE c.doc_type = 'event' AND ARRAY_CONTAINS(@types, c.type)")
        async for doc in self.cosmos.query_items(
                query, parameters=[{"name": "@types", "value": list(KEY_EVENT_TYPES)}],
                partition_key=m.data.match_id):
            prev = m.data.events.get(doc["event_id"])
            if prev is None or doc["version"] >= prev["version"]:
                m.data.events[doc["event_id"]] = doc

    # ---------- one trigger ----------

    async def explain(self, m: LiveMatch, trigger: dict) -> None:
        from insights.agents import Team
        from insights.workflow import run_trigger

        await asyncio.sleep(SETTLE_S)
        async with self.gate:
            try:
                async with m.lock:
                    await self.refresh_events(m)
                    m.data.triggers.append(trigger)
                    m.data.save(m.dir)
                    if m.team is None:
                        m.team = await Team(m.dir, self.credential).__aenter__()
                insight = await run_trigger(trigger, m.data, m.team)
                row = {"t": insight.play_ms, "received_at": time.time(),
                       **insight.model_dump(mode="json")}
                m.insights.append(row)
                self.counts["insights"] += 1
                log.info("insight %s %s %s %.1f s: %s", insight.trigger_id, insight.kind,
                         insight.caption_source, insight.latency_ms / 1000,
                         insight.captions["analyst.en"])
            except Exception:
                self.counts["errors"] += 1
                log.exception("insight failed for %s", trigger.get("trigger_id"))

    # ---------- HTTP ----------

    async def page(self, request: web.Request) -> web.Response:
        return web.Response(text=LIVE_PAGE.read_text(), content_type="text/html")

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"up_s": round(time.time() - self.started), **self.counts,
                                  "matches": sorted(self.matches),
                                  "last_error": self.last_error})

    async def list_matches(self, request: web.Request) -> web.Response:
        rows = []
        for mid, m in self.matches.items():
            if not m.data.prematch:
                continue
            last = max((i["received_at"] for i in m.insights), default=0)
            rows.append({"match_id": mid, "home": m.data.club_name(m.data.home),
                         "away": m.data.club_name(m.data.away), "insights": len(m.insights),
                         "last_at": last})
        return web.json_response(sorted(rows, key=lambda r: -r["last_at"]))

    async def list_insights(self, request: web.Request) -> web.Response:
        m = self.matches.get(request.query.get("match_id", ""))
        since = float(request.query.get("since", 0))
        rows = [i for i in (m.insights if m else []) if i["received_at"] > since]
        return web.json_response({"insights": rows, "now": time.time()})

    def app(self) -> web.Application:
        app = web.Application()
        app.add_routes([web.get("/", self.page), web.get("/health", self.health),
                        web.get("/api/matches", self.list_matches),
                        web.get("/api/insights", self.list_insights)])
        return app


async def main() -> None:
    from azure.cosmos.aio import CosmosClient
    from azure.eventhub.aio import EventHubConsumerClient
    from azure.identity.aio import DefaultAzureCredential

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for noisy in ("azure", "uamqp", "httpx", "mcp", "agent_framework"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    namespace = os.environ["EVENTHUB_NAMESPACE"]
    cred = DefaultAzureCredential()
    cosmos = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=cred)
    container = cosmos.get_database_client("offball").get_container_client("events")
    svc = InsightService(cred, container, namespace)
    # The page and /health come up first, so a failing input shows its error instead of crashing
    runner = web.AppRunner(svc.app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", "8080"))).start()
    log.info("insights service up: stats lookback %s, triggers from now", STATS_LOOKBACK)
    stats_from = datetime.now(timezone.utc) - STATS_LOOKBACK
    while True:
        try:
            stats = EventHubConsumerClient(fully_qualified_namespace=namespace,
                                           eventhub_name="stats", consumer_group="insights",
                                           credential=cred)
            triggers = EventHubConsumerClient(fully_qualified_namespace=namespace,
                                              eventhub_name="triggers", consumer_group="agents",
                                              credential=cred)
            async with stats, triggers:
                await asyncio.gather(
                    stats.receive(svc.on_stats, starting_position=stats_from),
                    # Only new triggers: a restart must not re-explain (and re-bill) old ones
                    triggers.receive(svc.on_trigger, starting_position="@latest"))
        except Exception as e:
            svc.last_error = "".join(traceback.format_exception_only(e))[-1000:]
            log.exception("hub readers stopped; retrying in 30 s")
        stats_from = datetime.now(timezone.utc) - timedelta(minutes=10)
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
