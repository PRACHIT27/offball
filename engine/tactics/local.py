import argparse
import json
import time
from collections import Counter
from pathlib import Path

from engine.local import run
from engine.tactics.config import TacticsConfig
from engine.tactics.engine import TacticsEngine
from engine.tactics.scoring import score

FILES = {"window": "windows.jsonl", "series": "series.jsonl", "territory": "territory.jsonl",
         "note": "notes.jsonl"}


def run_tactics(feeds_dir: Path, match_id: str, cfg: TacticsConfig | None = None) -> list[dict]:
    outputs, _ = run(feeds_dir, match_id)
    eng = TacticsEngine(match_id, cfg)
    results: list[dict] = []
    for msg in outputs:
        results += eng.dispatch(msg)
    results += eng.flush()
    return results


def write(results: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    try:
        for r in results:
            name = "triggers.jsonl" if r["sink"] == "triggers" else FILES[r["kind"]]
            if name not in handles:
                handles[name] = (out_dir / name).open("w", encoding="utf-8")
            handles[name].write(json.dumps(r, separators=(",", ":")) + "\n")
    finally:
        for h in handles.values():
            h.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Tactical Intelligence on local feed files")
    ap.add_argument("--feeds", type=Path, required=True)
    ap.add_argument("--match", required=True)
    ap.add_argument("--out", type=Path, default=Path("local_out"))
    ap.add_argument("--answer-key", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    t0 = time.perf_counter()
    results = run_tactics(args.feeds, args.match, TacticsConfig.load(args.config))
    out = args.out / args.match / "tactics"
    write(results, out)
    kinds = Counter(r.get("kind") or r["type"] for r in results)
    print(f"match {args.match}: {len(results)} outputs in {time.perf_counter() - t0:.1f} s")
    print(f"outputs: {dict(kinds)}")
    for t in (r for r in results if r["sink"] == "triggers"):
        ev = t["evidence"]
        print(f"  {t['trigger_id']} {t['period']}:{t['at_ms'] / 60000:5.1f}' {t['type']:<11}"
              f" {t['reason']:<13} {t['team_id'] or '-':<4} imp {t['importance']}"
              f" before {ev['before'].get('line_height_m', '')} after"
              f" {ev['after'].get('line_height_m', '') if isinstance(ev['after'], dict) else ''}")
    if args.answer_key:
        key = json.loads(args.answer_key.read_text())
        report = score(key, [r for r in results if r.get("kind") == "note"])
        (out / "scoring.json").write_text(json.dumps(report, indent=1))
        print(f"answer key: found {report['found']} of {report['true_changes']} changes, "
              f"{report['false_alarms']} false alarms, average lag {report['average_lag_s']} s")
    print(f"written to {out}")


if __name__ == "__main__":
    main()
