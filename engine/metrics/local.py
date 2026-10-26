"""Local mode (PM-28): feed files → normalizers → merge stage → Performance Metrics, no Azure.

    python -m engine.metrics.local --feeds local_feeds/fx01/feeds --out local_out --match fx01

Writes local_out/metrics/{match}/stats.jsonl, cues.jsonl and metrics.json.
"""

import argparse
import time
from collections import Counter
from pathlib import Path

from engine.local import Pipeline, messages
from engine.metrics.models import PassValues, PressureSample
from engine.metrics.publisher import LocalSink, Publisher
from engine.metrics.router import MetricsEngine


def run_metrics(feeds_dir: Path, out_dir: Path, match_id: str,
                to_tactics=()) -> tuple[MetricsEngine, Publisher]:
    pipe = Pipeline(match_id)
    engine = MetricsEngine(match_id)
    sink = LocalSink(out_dir, match_id)
    pub = Publisher([sink], to_tactics)
    last = 0.0
    for msg in messages(feeds_dir):
        for clean in pipe.process(msg):
            pub.emit(engine.dispatch(clean))
        last = msg.wall_ms
    for clean in pipe.stage.flush(last):
        pub.emit(engine.dispatch(clean))
    pub.emit(engine.flush())
    sink.close()
    return engine, pub


def main() -> None:
    ap = argparse.ArgumentParser(description="OffBall Performance Metrics in local mode")
    ap.add_argument("--feeds", type=Path, required=True, help="folder with feed_a/feed_b.jsonl")
    ap.add_argument("--out", type=Path, default=Path("local_out"))
    ap.add_argument("--match", required=True)
    args = ap.parse_args()

    tactics: Counter = Counter()

    def count(r: PressureSample | PassValues) -> None:
        tactics[r.kind] += 1

    t0 = time.perf_counter()
    engine, pub = run_metrics(args.feeds, args.out, args.match, [count])
    print(f"match {args.match}: done in {time.perf_counter() - t0:.1f} s")
    for k, v in sorted(pub.counts.items()):
        print(f"  {k}: {v}")
    t = engine.totals
    ids = engine.roster.ids
    top = sorted(range(len(ids)), key=lambda c: -t.distance[c])[:5]
    print("most distance: " + ", ".join(f"{ids[c]} {t.distance[c] / 1000:.2f} km" for c in top))
    print(f"out: {args.out / 'metrics' / args.match}")


if __name__ == "__main__":
    main()
