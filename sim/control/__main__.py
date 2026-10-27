import argparse
import os

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m sim.control",
                                 description="OffBall match control page")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dry-run", action="store_true",
                    help="count messages instead of sending them to Event Hubs")
    args = ap.parse_args()
    if args.dry_run:
        os.environ["STREAM_TARGET"] = "dry-run"
    uvicorn.run("sim.control.app:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
