"""Build the Performance Metrics view for the viewer screen: a side file next to each replay.

    PYTHONPATH=. python scripts/build_metrics_view.py --storyline red_card --match m001

Writes web/public/replays/{match_id}.metrics.json without touching {match_id}.json (which also
carries Insight Generation's captions). The storyline is simulated again; simulation is
deterministic per storyline, so it is the same match the replay shows. Contents, all from the
engine's metrics outputs (never the answer key):
- heat: each player's 21 × 14 heatmap (whole match and last 15 min), every 5 minutes, in
  per-mille shares of their frames;
- shots: position, xG, shot speed and outcome;
- passing: per team every minute, cumulative attempts, accuracy, average difficulty and
  completion vs expected;
- pressure: each player's pressure (0–100) once a second;
- cues: distance milestones and shot speeds with their anchors.
"""

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np

from engine.local import run
from engine.merge.outputs import EventDelete, EventUpsert
from engine.metrics.models import Cue, StatsMessage
from engine.metrics.router import MetricsEngine
from ingest.clean import PERIOD_BASE_MS

HEAT_EVERY_MS = 300_000
PASSING_EVERY_MS = 60_000
CUE_KINDS = {"distance_milestone", "shot_speed"}


def per_mille(grid) -> list[list[int]] | None:
    return None if grid is None else np.rint(np.asarray(grid) * 1000).astype(int).tolist()


def build(feeds: Path, match_id: str) -> dict:
    outputs, _ = run(feeds, match_id)
    engine = MetricsEngine(match_id)
    stats: list[StatsMessage] = []
    cues: dict[str, dict] = {}
    events: dict[str, object] = {}
    for msg in outputs:
        if isinstance(msg, EventUpsert | EventDelete):
            ev = msg.event
            if ev.event_id not in events or ev.version >= events[ev.event_id].version:
                events[ev.event_id] = ev
        for r in engine.dispatch(msg):
            if isinstance(r, StatsMessage):
                stats.append(r)
            elif isinstance(r, Cue) and r.kind in CUE_KINDS:
                cues[r.cue_id] = r.model_dump(mode="json")
    for r in engine.flush():
        if isinstance(r, StatsMessage):
            stats.append(r)

    # Same continuous play time as scripts/build_replay.py (period 2's clock overlaps 1's)
    p1_end = max((s.match_clock_ms for s in stats if s.kind == "positions" and s.period == 1),
                 default=PERIOD_BASE_MS[2])

    def t(period: int, clock: int) -> int:
        return clock if period == 1 else p1_end + (clock - PERIOD_BASE_MS[2])

    order = engine.roster.ids
    heat, pressure, last_heat, last_pressure = [], [], -HEAT_EVERY_MS, -1000
    for s in stats:
        now = t(s.period, s.match_clock_ms)
        if s.kind == "heatmap":
            if now - last_heat >= HEAT_EVERY_MS or (heat and heat[-1]["t"] == now):
                if not heat or heat[-1]["t"] != now:
                    heat.append({"t": now, "players": {}})
                    last_heat = now
                for pid, maps in s.values["players"].items():
                    if maps["match"] is not None:
                        heat[-1]["players"][pid] = {"match": per_mille(maps["match"]),
                                                    "last_15": per_mille(maps["last_15"])}
        elif s.kind == "positions" and now - last_pressure >= 1000:
            tags = s.values["tags"]
            pressure.append([now, [round(tags[pid]["pressure"] * 100) if pid in tags else -1
                                   for pid in order]])
            last_pressure = now

    # Final version of every pass and shot result
    latest: dict[str, StatsMessage] = {}
    for s in stats:
        if s.kind in ("pass", "shot"):
            key = s.evidence.event_ids[0]
            if key not in latest or s.version >= latest[key].version:
                latest[key] = s
    finals = sorted((s for s in latest.values() if s.status == "active"),
                    key=lambda s: t(s.period, s.match_clock_ms))

    shots = []
    for s in finals:
        if s.kind != "shot":
            continue
        ev = events.get(s.evidence.event_ids[0])
        start = ev.start if ev is not None else None
        shots.append({"t": t(s.period, s.match_clock_ms), "id": s.evidence.event_ids[0],
                      "team": s.team_id, "player": s.player_id,
                      "x": round(start.x, 1) if start else None,
                      "y": round(start.y, 1) if start else None,
                      "xg": s.values["xg"], "speed_kmh": s.values["speed_kmh"],
                      "outcome": s.values["outcome"]})

    passing, acc = [], {}
    next_cut = PASSING_EVERY_MS
    passes = [s for s in finals if s.kind == "pass"]
    end_t = t(2, max((s.match_clock_ms for s in stats if s.period == 2), default=0))
    i = 0
    while next_cut <= end_t + PASSING_EVERY_MS:
        while i < len(passes) and t(passes[i].period, passes[i].match_clock_ms) <= next_cut:
            p = passes[i]
            a = acc.setdefault(p.team_id, {"attempts": 0, "completed": 0, "difficulty": 0.0,
                                           "expected": 0.0})
            a["attempts"] += 1
            a["completed"] += int(p.values["completed"])
            a["difficulty"] += p.values["difficulty"]
            a["expected"] += p.values["p_complete"]
            i += 1
        passing.append({"t": next_cut, "teams": {
            team: {"attempts": a["attempts"],
                   "accuracy": round(a["completed"] / a["attempts"], 3),
                   "avg_difficulty": round(a["difficulty"] / a["attempts"], 1),
                   "completion_vs_expected": round(a["completed"] - a["expected"], 1)}
            for team, a in acc.items() if a["attempts"]}})
        next_cut += PASSING_EVERY_MS

    return {
        "schema": "offball-metrics/1", "match_id": match_id, "order": order,
        "heat": {"grid": [21, 14], "snapshots": heat},
        "shots": shots, "passing": passing, "pressure": pressure,
        "cues": sorted(({"t": t(c["period"], c["start_clock_ms"]), "kind": c["kind"],
                         "duration_ms": c["duration_ms"], "anchor": c["anchor"],
                         "data": c["data"]} for c in cues.values() if c["status"] == "on_air"),
                       key=lambda c: c["t"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the metrics side file for a replay")
    ap.add_argument("--storyline", required=True)
    ap.add_argument("--match", required=True, help="match ID of the replay it goes with")
    ap.add_argument("--out", type=Path, default=Path("web/public/replays"))
    args = ap.parse_args()

    from sim.output import generate
    from sim.storyline import load

    tmp = Path(tempfile.mkdtemp(prefix="offball-metrics-"))
    m = generate(load(args.storyline, None), tmp, "light")
    if m.truth.match_id != args.match:
        raise SystemExit(f"storyline {args.storyline} is match {m.truth.match_id}, "
                         f"not {args.match}")
    view = build(m.feeds_dir, m.truth.match_id)
    path = args.out / f"{args.match}.metrics.json"
    path.write_text(json.dumps(view, separators=(",", ":")))
    print(f"{path}: {path.stat().st_size / 1e6:.2f} MB, {len(view['shots'])} shots, "
          f"{len(view['heat']['snapshots'])} heatmap snapshots, {len(view['cues'])} cues")


if __name__ == "__main__":
    main()
