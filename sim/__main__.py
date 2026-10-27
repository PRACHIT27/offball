import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from sim.output import generate
from sim.storyline import BUILT_IN, load


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m sim", description="OffBall match simulation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="simulate a match and write feeds + answer key")
    g.add_argument("--storyline", default="red_card",
                   help=f"built-in ({', '.join(BUILT_IN)}), random (use --seed) or a JSON file")
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--mess", choices=["off", "light", "full"], default="light")
    g.add_argument("--minutes", type=float, default=None,
                   help="period length in minutes (default: 45 + stoppage)")
    g.add_argument("--seed", type=int, default=None)
    s = sub.add_parser("stream", help="send generated feeds to the raw hubs")
    s.add_argument("--feeds", type=Path, required=True)
    s.add_argument("--speed", type=float, default=10.0)
    s.add_argument("--env", type=Path, default=Path(".env"))
    args = ap.parse_args()

    if args.cmd == "generate":
        story = load(args.storyline, args.seed)
        period_s = (args.minutes * 60, args.minutes * 60) if args.minutes else (2790.0, 2880.0)
        t0 = time.perf_counter()
        m = generate(story, args.out, args.mess, period_s=period_s)
        kinds = Counter(e["type"] for e in m.truth.events)
        t, sc = m.truth, m.truth.score
        print(f"match {t.match_id} ({story.name}): {t.home} {sc[t.home]}-{sc[t.away]} {t.away}"
              f" in {time.perf_counter() - t0:.1f} s")
        print(f"events: {dict(kinds)}")
        print(f"tactic changes: {len(m.truth.tactic_changes)}")
        print(f"feeds: {m.feeds_dir}\nanswer key: {m.answer_key_dir}")
    else:
        from tests.fixturegen import stream
        sys.argv = ["stream", "--feeds", str(args.feeds), "--speed", str(args.speed),
                    "--env", str(args.env)]
        stream.main()


if __name__ == "__main__":
    main()
