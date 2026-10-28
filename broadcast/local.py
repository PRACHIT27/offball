"""Broadcast in local mode: a match from feed files, through the real engine (merge stage,
Performance Metrics, Tactical Intelligence), into the cue manager at match speed, with a
built-in WebSocket push instead of Web PubSub. No Azure.

    python -m broadcast.local --feeds local_feeds/m001/feeds --match m001 --speed 5
    # screen: cd web && VITE_CUES_URL=http://localhost:8080 npm run dev, pick the LIVE match
    # producer console: http://localhost:8080/producer (passcode "local")
"""

import argparse
import asyncio
from pathlib import Path

from aiohttp import WSMsgType, web

from broadcast.service import CueService
from engine.local import Pipeline, messages
from engine.metrics.models import Cue, StatsMessage
from engine.metrics.router import MetricsEngine
from engine.tactics.engine import TacticsEngine

BATCH_MS = 200


class LocalPush:
    """Web PubSub stand-in: one WebSocket per viewer, groups by match."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.groups: dict[str, set[web.WebSocketResponse]] = {}

    async def send_to_group(self, group_name: str, message: str, content_type=None) -> None:
        for ws in list(self.groups.get(group_name, ())):
            try:
                await ws.send_str(message)
            except ConnectionResetError:
                self.groups[group_name].discard(ws)

    async def get_client_access_token(self, groups=None, minutes_to_expire=60) -> dict:
        return {"url": f"ws://localhost:{self.port}/ws?group={groups[0]}"}

    async def handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        members = self.groups.setdefault(request.query.get("group", ""), set())
        members.add(ws)
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
        members.discard(ws)
        return ws


def hub_messages(outputs) -> list[tuple[dict, dict]]:
    """Engine results as the `stats` hub carries them: (body, properties)."""
    out = []
    for r in outputs:
        if isinstance(r, StatsMessage | Cue):
            out.append((r.model_dump(mode="json"),
                        {"type": "cue" if isinstance(r, Cue) else "stats", "kind": r.kind,
                         "match_id": r.match_id}))
        elif isinstance(r, dict) and r.get("sink") == "stats":
            out.append((r, {"kind": r.get("kind"), "match_id": r.get("match_id")}))
    return out


async def feed(svc: CueService, feeds: Path, match_id: str, speed: float) -> None:
    pipe, metrics, tactics = Pipeline(match_id), MetricsEngine(match_id), TacticsEngine(match_id)
    m = svc.match(match_id)
    for raw in messages(feeds):
        for clean in pipe.process(raw):
            if clean.kind == "prematch":
                m.prematch = clean.prematch
            results = metrics.dispatch(clean) + tactics.dispatch(clean)
            for body, props in hub_messages(results):
                svc.publish(match_id, m.on_stats(body, props))
            if clean.kind == "frames":
                await asyncio.sleep(BATCH_MS / 1000 / speed)


async def main_async(args) -> None:
    push = LocalPush(args.port)
    svc = CueService(push, passcode="local")
    app = svc.app()
    app.router.add_get("/ws", push.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", args.port).start()
    print(f"cue manager on http://localhost:{args.port} (producer console: /producer, "
          f"passcode 'local'); streaming {args.match} at {args.speed}x", flush=True)
    sender = asyncio.create_task(svc.sender())
    await feed(svc, args.feeds, args.match, args.speed)
    print("match finished; still serving (Ctrl-C to stop)", flush=True)
    await asyncio.Event().wait()
    sender.cancel()


def main() -> None:
    ap = argparse.ArgumentParser(description="Broadcast cue manager in local mode")
    ap.add_argument("--feeds", type=Path, required=True)
    ap.add_argument("--match", required=True)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--port", type=int, default=8080)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
