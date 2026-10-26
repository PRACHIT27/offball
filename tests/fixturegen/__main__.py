"""python -m tests.fixturegen --out local_feeds/fx01 --mess light"""

import argparse
from pathlib import Path

from tests.fixturegen.generate import generate


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a fixture match (feeds + answer key)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--match", default="fx01")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--mess", choices=["off", "light", "full"], default="light")
    ap.add_argument("--minutes", type=float, default=None,
                    help="period length in minutes (default: 45 + stoppage)")
    args = ap.parse_args()
    period_s = (args.minutes * 60, args.minutes * 60) if args.minutes else (2790.0, 2880.0)
    fx = generate(args.out, args.match, args.seed, args.mess, period_s=period_s)
    print(f"feeds: {fx.feeds_dir}\nanswer key: {fx.answer_key_dir}\n"
          f"events: {len(fx.truth.events)}  clock offset: {fx.clock_offset_ms} ms")


if __name__ == "__main__":
    main()
