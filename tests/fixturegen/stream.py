"""Stand-in for `python -m sim stream`: send fixture feed files to the raw hubs at a set speed.

    python -m tests.fixturegen.stream --feeds local_feeds/fx01/feeds --speed 10

Uses EVENTHUB_CONNECTION from .env (local developer tool; never printed). Partition key is the
match ID; `emitted_at` is re-stamped with the real send time, as the real streamer does.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from engine.local import messages

HUBS = {"A": "raw-events", "B": "raw-tracking"}


def schedule(feeds_dir: Path, speed: float) -> list[tuple[float, str, str, dict]]:
    """(seconds after start, feed, body, properties) in send order."""
    msgs = list(messages(feeds_dir))
    t0 = msgs[0].wall_ms
    return [((m.wall_ms - t0) / 1000 / speed, m.feed, m.body, m.properties) for m in msgs]


def _env(path: Path, key: str) -> str:
    for line in path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} not found in {path}")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def main() -> None:
    from azure.eventhub import EventData, EventHubProducerClient

    ap = argparse.ArgumentParser(description="Replay fixture feeds into the raw hubs")
    ap.add_argument("--feeds", type=Path, required=True)
    ap.add_argument("--speed", type=float, default=10.0)
    ap.add_argument("--env", type=Path, default=Path(".env"))
    args = ap.parse_args()

    plan = schedule(args.feeds, args.speed)
    conn = _env(args.env, "EVENTHUB_CONNECTION")
    producers = {f: EventHubProducerClient.from_connection_string(conn, eventhub_name=h)
                 for f, h in HUBS.items()}
    start = time.monotonic()
    i, sent, last_report = 0, {"A": 0, "B": 0}, 0.0
    try:
        while i < len(plan):
            wait = plan[i][0] - (time.monotonic() - start)
            if wait > 0:
                time.sleep(min(wait, 0.05))
                continue
            due: dict[str, list] = {"A": [], "B": []}
            while i < len(plan) and plan[i][0] <= time.monotonic() - start:
                _, feed, body, props = plan[i]
                event = EventData(body)
                event.properties = {**props, "emitted_at": _now()}
                due[feed].append(event)
                i += 1
            for feed, events in due.items():
                if not events:
                    continue
                match_id = events[0].properties["match_id"]
                batch = producers[feed].create_batch(partition_key=match_id)
                for e in events:
                    try:
                        batch.add(e)
                    except ValueError:
                        producers[feed].send_batch(batch)
                        batch = producers[feed].create_batch(partition_key=match_id)
                        batch.add(e)
                producers[feed].send_batch(batch)
                sent[feed] += len(events)
            if time.monotonic() - last_report > 10:
                last_report = time.monotonic()
                print(json.dumps({"elapsed_s": round(last_report - start), "sent": sent,
                                  "of": len(plan)}), flush=True)
    finally:
        for p in producers.values():
            p.close()
    print(json.dumps({"done": True, "sent": sent, "seconds": round(time.monotonic() - start)}))


if __name__ == "__main__":
    main()
