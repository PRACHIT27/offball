"""Load a match into the Fabric Eventhouse (Platform PL-18), through the real engine.

Runs the feed files through the merge stage, Performance Metrics and Tactical Intelligence,
exactly as the engine does in Azure, and streams what it would publish on `stats` and `triggers`
into the KQL database, timed by each raw message's `emitted_at`. Also records the merge stage's
ingestion counts each match minute and how long each engine step took. Re-running a match
replaces its rows. Keyless: uses your az login.

    PYTHONPATH=. python scripts/fabric_load.py --feeds out/m001/feeds --match m001 \
        --storyline red_card --kusto https://<eventhouse query uri>
"""

import argparse
import asyncio
import time
from pathlib import Path

import aiohttp
from azure.identity.aio import DefaultAzureCredential

from broadcast.fabric import SCHEMA, KustoSink, iso, match_row, rows
from engine.local import Pipeline, messages
from engine.metrics.models import Cue, StatsMessage
from engine.metrics.router import MetricsEngine
from engine.tactics.engine import TacticsEngine

LATENCY_EVERY = 25  # frame batches (5 s of play)
FLUSH_ROWS = 20_000


def body_of(r) -> dict | None:
    if isinstance(r, StatsMessage | Cue):
        return r.model_dump(mode="json")
    return r if isinstance(r, dict) else None


async def load(args) -> None:
    async with DefaultAzureCredential() as cred, aiohttp.ClientSession() as session:
        sink = KustoSink(args.kusto, cred, session)
        await sink.ensure_tables()
        for t in SCHEMA:
            await sink.command(f".delete table {t} records <| {t} | where match_id == "
                               f"'{args.match}'")
        pipe, metrics, tactics = Pipeline(args.match), MetricsEngine(args.match), \
            TacticsEngine(args.match)
        batches = rows_n = 0
        minute_seen = -1
        kickoff = None
        for raw in messages(args.feeds):
            at = iso(raw.wall_ms)
            kickoff = kickoff or at
            t0 = time.perf_counter()
            cleans = pipe.process(raw)
            merge_ms = (time.perf_counter() - t0) * 1000
            for clean in cleans:
                if clean.kind == "prematch":
                    sink.add("Matches", match_row(args.match, clean.prematch, kickoff,
                                                  args.storyline))
                t1 = time.perf_counter()
                m_out = metrics.dispatch(clean)
                t2 = time.perf_counter()
                t_out = tactics.dispatch(clean)
                t3 = time.perf_counter()
                for r in m_out + t_out:
                    body = body_of(r)
                    if body is not None:
                        pairs = rows(at, body, {"type": "cue"} if isinstance(r, Cue) else {})
                        sink.extend(pairs)
                        rows_n += len(pairs)
                if clean.kind != "frames":
                    continue
                batches += 1
                minute = clean.batch.frames[-1].match_clock_ms // 60_000
                if batches % LATENCY_EVERY == 0:
                    for step, ms in (("merge", merge_ms), ("metrics", (t2 - t1) * 1000),
                                     ("tactics", (t3 - t2) * 1000)):
                        sink.add("Latency", {"at": at, "match_id": args.match, "step": step,
                                             "ms": round(ms, 3), "minute": float(minute)})
                if minute != minute_seen:
                    minute_seen = minute
                    sink.add("Ingest", {"at": at, "match_id": args.match,
                                        "minute": float(minute),
                                        "counts": dict(pipe.stage.counts),
                                        "dead_letters": len(pipe.dead_letters)})
            if rows_n >= FLUSH_ROWS:
                await sink.flush()
                rows_n = 0
        await sink.flush()
        print(f"{args.match}: {sink.sent} rows sent, {sink.failed} failed")


def main() -> None:
    ap = argparse.ArgumentParser(description="Load a match into the Fabric Eventhouse")
    ap.add_argument("--feeds", type=Path, required=True)
    ap.add_argument("--match", required=True)
    ap.add_argument("--storyline", default="")
    ap.add_argument("--kusto", required=True, help="Eventhouse query service URI")
    asyncio.run(load(ap.parse_args()))


if __name__ == "__main__":
    main()
