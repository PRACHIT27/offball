"""Results numbers for the submission: run storylines end to end and score them.

    PYTHONPATH=. python scripts/results.py                       # all six storylines, light mess
    PYTHONPATH=. python scripts/results.py --storylines red_card switch --minutes 10

Each match is simulated, sent through both messy provider feeds, cleaned and merged (Data
Ingestion), then measured (Performance Metrics) and read tactically (Tactical Intelligence), as
the live engine does. Only this evaluation script reads the answer keys. Writes
results/results.json and results/RESULTS.md.
"""

import argparse
import json
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np

from engine.local import run
from engine.merge.outputs import FramesOut
from engine.metrics.models import Cue, StatsMessage
from engine.metrics.router import MetricsEngine
from engine.tactics.engine import TacticsEngine
from engine.tactics.scoring import score as score_tactics
from sim.output import generate
from sim.storyline import BUILT_IN, load
from tests.evaluate import score as score_ingestion

MIN_DISTANCE_M = 500  # players who barely played make percentage errors meaningless


def evaluate(storyline: str, mess: str, minutes: float | None) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"offball-results-{storyline}-"))
    period_s = (minutes * 60, minutes * 60) if minutes else (2790.0, 2880.0)
    m = generate(load(storyline, None), tmp, mess, period_s=period_s)
    key = json.loads((m.answer_key_dir / "answer_key.json").read_text())

    t0 = time.perf_counter()
    outputs, pipe = run(m.feeds_dir, key["match_id"])
    ingest_s = time.perf_counter() - t0

    metrics, tactics = MetricsEngine(key["match_id"]), TacticsEngine(key["match_id"])
    results, batch_ms = [], []
    t0 = time.perf_counter()
    for msg in outputs:
        t1 = time.perf_counter()
        results += metrics.dispatch(msg) + tactics.dispatch(msg)
        if isinstance(msg, FramesOut):
            batch_ms.append((time.perf_counter() - t1) * 1000)
    results += metrics.flush() + tactics.flush()
    engine_s = time.perf_counter() - t0

    # Data Ingestion: events recovered from the two messy feeds, clock offset found
    ing = score_ingestion(outputs, key)
    offset_err = abs(pipe.stage.offset_ms - key["clock_offset_ms"])

    # Tactical Intelligence: detected changes vs the scripted ones
    notes = [r for r in results if isinstance(r, dict) and r.get("kind") == "note"]
    triggers = [r for r in results if isinstance(r, dict) and r.get("sink") == "triggers"]
    tac = score_tactics(key, notes)

    # Performance Metrics: player stats vs the simulator's truth
    dist_err, top_ok, sprint_ok = [], [], []
    for pid, truth in key["true_player_stats"].items():
        c = metrics.roster.col.get(pid)
        if c is None or truth["distance_m"] < MIN_DISTANCE_M:
            continue
        t = metrics.totals
        dist_err.append(abs(t.distance[c] / truth["distance_m"] - 1) * 100)
        top_ok.append(abs(t.top_speed[c] - truth["top_speed_ms"]) <= 0.3)
        sprint_ok.append(abs(int(t.sprints[c]) - truth["sprints"]) <= 2)
    kinds = Counter(r.kind for r in results if isinstance(r, StatsMessage | Cue))
    cues = [r for r in results if isinstance(r, Cue)]

    return {
        "storyline": storyline, "match_id": key["match_id"], "mess": mess,
        "score": key["score"],
        "ingestion": {"events_recovered_pct": round(ing.recovery * 100, 1),
                      "true_events": ing.true_total, "extra_events": len(ing.extra_active),
                      "clock_offset_error_ms": offset_err,
                      "dead_letters": len(pipe.dead_letters),
                      "seconds": round(ingest_s, 1)},
        "tactics": {"true_changes": tac["true_changes"], "found": tac["found"],
                    "false_alarms": tac["false_alarms"], "average_lag_s": tac["average_lag_s"],
                    "triggers": len(triggers),
                    "trigger_types": dict(Counter(t["type"] for t in triggers))},
        "metrics": {"players": len(dist_err),
                    "distance_error_median_pct": round(statistics.median(dist_err), 1),
                    "top_speed_within_0_3_pct": round(100 * np.mean(top_ok), 1),
                    "sprints_within_2_pct": round(100 * np.mean(sprint_ok), 1),
                    "passes": kinds["pass"], "shots": kinds["shot"],
                    "cues_on_air": sum(c.status == "on_air" for c in cues),
                    "cues_withdrawn": sum(c.status == "withdrawn" for c in cues)},
        "engine": {"seconds_per_match": round(engine_s, 1),
                   "frame_batch_p95_ms": round(float(np.percentile(batch_ms, 95)), 2),
                   "frame_batch_max_ms": round(max(batch_ms), 2)},
    }


def markdown(rows: list[dict]) -> str:
    lines = ["# OffBall results", "",
             f"{len(rows)} simulated matches, `{rows[0]['mess']}` feed mess, full pipeline "
             "(two messy feeds → ingestion → metrics + tactics), scored against each match's "
             "hidden answer key by `scripts/results.py`.", "",
             "| Storyline | Events recovered | Clock offset error | Tactic changes found | "
             "False alarms | Avg lag | Distance error (median) | Top speed ±0.3 m/s | "
             "Sprints ±2 | Engine p95 per batch |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        i, t, m, e = r["ingestion"], r["tactics"], r["metrics"], r["engine"]
        lag = f"{t['average_lag_s']} s" if t["average_lag_s"] is not None else "–"
        lines.append(
            f"| {r['storyline']} | {i['events_recovered_pct']}% | {i['clock_offset_error_ms']} ms"
            f" | {t['found']} of {t['true_changes']} | {t['false_alarms']} | {lag} | "
            f"{m['distance_error_median_pct']}% | {m['top_speed_within_0_3_pct']}% | "
            f"{m['sprints_within_2_pct']}% | {e['frame_batch_p95_ms']} ms |")
    found = sum(r["tactics"]["found"] for r in rows)
    true = sum(r["tactics"]["true_changes"] for r in rows)
    fa = sum(r["tactics"]["false_alarms"] for r in rows)
    rec = statistics.mean(r["ingestion"]["events_recovered_pct"] for r in rows)
    lines += ["", "**Totals:**",
              f"- Tactic changes detected: **{found} of {true}** "
              f"({round(100 * found / true) if true else 0}%), {fa} false alarms.",
              f"- Events recovered from the messy feeds: **{rec:.1f}%** on average.",
              f"- Triggers raised for the agents: {sum(r['tactics']['triggers'] for r in rows)}.",
              ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score storylines end to end against answer keys")
    ap.add_argument("--storylines", nargs="+", default=list(BUILT_IN))
    ap.add_argument("--mess", choices=["off", "light", "full"], default="light")
    ap.add_argument("--minutes", type=float, default=None, help="period length for quick runs")
    ap.add_argument("--out", type=Path, default=Path("results"))
    args = ap.parse_args()

    rows = []
    for s in args.storylines:
        r = evaluate(s, args.mess, args.minutes)
        rows.append(r)
        print(f"{s}: ingestion {r['ingestion']['events_recovered_pct']}%, tactics "
              f"{r['tactics']['found']}/{r['tactics']['true_changes']} "
              f"(+{r['tactics']['false_alarms']} false), distance err "
              f"{r['metrics']['distance_error_median_pct']}%", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(rows, indent=1))
    (args.out / "RESULTS.md").write_text(markdown(rows))
    print(markdown(rows))


if __name__ == "__main__":
    main()
