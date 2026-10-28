"""Insight Generation in local mode: run a match through the engine, then write an insight per
trigger, and optionally add them to a viewer replay file.

    python -m insights.local --feeds local_feeds/m001/feeds --match m001 \
        --replay web/public/replays/m001.json

Without `--agents` every caption is a template (IG-31). With it, the agent team writes them on
Foundry (az login with access to the AI Services resource).
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from engine.local import run
from engine.tactics.engine import TacticsEngine
from insights import facts, templates
from insights.data import MatchData
from insights.models import Insight


def collect(feeds: Path, match_id: str) -> MatchData:
    """Ingestion and Tactical Intelligence in-process, exactly as the live engine runs them."""
    outputs, _ = run(feeds, match_id)
    data, tactics = MatchData(match_id), TacticsEngine(match_id)
    for msg in outputs:
        data.add_merge_output(msg)
        for r in tactics.dispatch(msg):
            data.add_tactics(r)
    for r in tactics.flush():
        data.add_tactics(r)
    return data


def template_insight(trigger: dict, data: MatchData) -> Insight:
    f = facts.build(trigger, data)
    return Insight(
        insight_id=trigger["trigger_id"].replace("t-", "i-"), trigger_id=trigger["trigger_id"],
        match_id=data.match_id, kind=f["kind"], period=f["period"], at_ms=f["at_ms"],
        play_ms=f["play_ms"], team_id=f["team"], text_en_core=templates.core_text(f),
        captions=templates.captions(f), evidence=f["evidence"], caption_source="template")


async def agent_insights(data: MatchData, data_dir: Path, concurrency: int) -> list[Insight]:
    from azure.identity.aio import DefaultAzureCredential

    from insights.agents import Team
    from insights.workflow import run_trigger

    gate = asyncio.Semaphore(concurrency)

    async def one(trigger: dict) -> Insight:
        async with gate:
            i = await run_trigger(trigger, data, team)
            print(f"  {i.trigger_id} {i.kind:<10} {i.caption_source:<8}"
                  f" {i.latency_ms / 1000:5.1f} s  {i.captions['analyst.en']}", flush=True)
            return i

    async with DefaultAzureCredential() as cred, Team(data_dir, cred) as team:
        return list(await asyncio.gather(*(one(t) for t in data.triggers)))


def add_to_replay(path: Path, insights: list[Insight]) -> None:
    replay = json.loads(path.read_text())
    replay["insights"] = [{"t": i.play_ms, **i.model_dump(mode="json")} for i in insights]
    path.write_text(json.dumps(replay, separators=(",", ":")))


def main() -> None:
    ap = argparse.ArgumentParser(description="Insight Generation on local feed files")
    ap.add_argument("--feeds", type=Path, required=True)
    ap.add_argument("--match", required=True)
    ap.add_argument("--out", type=Path, default=Path("local_out"))
    ap.add_argument("--replay", type=Path, help="viewer replay file to add the insights to")
    ap.add_argument("--agents", action="store_true", help="write captions with the agent team")
    ap.add_argument("--concurrency", type=int, default=3, help="triggers handled at once")
    args = ap.parse_args()

    t0 = time.perf_counter()
    data_dir = args.out / args.match / "insights" / "data"
    if data_dir.exists():
        data = MatchData.load(data_dir, args.match)
    else:
        data = collect(args.feeds, args.match)
        data.save(data_dir)
    if args.replay and args.replay.exists():
        rep = json.loads(args.replay.read_text(encoding="utf-8"))
        data.add_metrics(rep.get("cues", []), rep.get("totals", []))
    if args.agents:
        insights = asyncio.run(agent_insights(data, data_dir, args.concurrency))
    else:
        insights = [template_insight(t, data) for t in data.triggers]
    out = args.out / args.match / "insights" / "insights.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for i in insights:
            f.write(i.model_dump_json() + "\n")
    took = time.perf_counter() - t0
    print(f"match {args.match}: {len(insights)} insights in {took:.1f} s -> {out}")
    if args.agents:
        lat = sorted(i.latency_ms for i in insights)
        agent = sum(i.caption_source == "agent" for i in insights)
        n = len(insights[0].captions) if insights else 15
        caps = sum(n - len(i.checker.template_keys) for i in insights)
        first_try = sum(i.checker.attempts == 1 and i.checker.passed for i in insights)
        print(f"agent insights: {agent}/{len(insights)}; agent captions {caps}/{n * len(insights)}"
              f"; first-try pass {first_try}"
              f"; latency median {lat[len(lat) // 2] / 1000:.1f} s, worst {lat[-1] / 1000:.1f} s")
    else:
        for i in insights:
            print(f"  {i.trigger_id} {i.kind:<10} {i.captions['analyst.en']}")
    if args.replay:
        add_to_replay(args.replay, insights)
        print(f"added to {args.replay}")


if __name__ == "__main__":
    main()
