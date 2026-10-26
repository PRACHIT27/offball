"""Write a fixture match: feed files for ingestion plus a separate answer key for evaluation."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from tests.fixturegen import mess
from tests.fixturegen.match import Script, Truth, simulate
from tests.fixturegen.providers import Clock, Msg, feed_a, feed_b

KICKOFF_WALL = datetime(2026, 10, 25, 14, 0, 0, tzinfo=UTC)


@dataclass
class Fixture:
    feeds_dir: Path
    answer_key_dir: Path
    truth: Truth
    clock_offset_ms: int
    mess_log: dict


def _compact(a: np.ndarray) -> np.ndarray:
    return a.astype(np.float32) if a.dtype == np.float64 else a


def iso(emitted_ms: float) -> str:
    t = KICKOFF_WALL + timedelta(milliseconds=round(emitted_ms))
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _write_feed(path: Path, msgs: list[Msg], match_id: str) -> None:
    with path.open("w") as f:
        for m in sorted(msgs, key=lambda m: m.emitted_ms):
            body = m.body if isinstance(m.body, str) else json.dumps(m.body, separators=(",", ":"))
            props = {"emitted_at": iso(m.emitted_ms), "feed": m.feed, "match_id": match_id}
            f.write(json.dumps({"properties": props, "body": body}, separators=(",", ":")) + "\n")


def generate(out_dir: Path, match_id: str = "fx01", seed: int = 42, mess_level: str = "light",
             rules: frozenset | None = None, period_s=(2790.0, 2880.0), halftime_s: float = 900.0,
             pause_b: tuple[float, float] | None = None, script: Script | None = None) -> Fixture:
    """`rules` overrides `mess_level`. `pause_b` = (start, duration) in wall seconds."""
    rules = mess.LEVELS[mess_level] if rules is None else rules
    rng = np.random.default_rng(seed + 1)
    truth = simulate(match_id, seed, period_s, script)
    clock = Clock(truth.period_length_ms(1), int(halftime_s * 1000))
    offset_ms = int(rng.integers(500, 2001)) if "a_clock_offset" in rules else 0
    log: dict = {}

    a = mess.apply_feed_a(rules, feed_a(truth, clock, offset_ms), truth, rng, log)
    b = feed_b(truth, clock, rng, noise_cm=10.0 if "b_noise" in rules else 0.0)
    b = mess.apply_feed_b(rules, b, rng, log)
    if pause_b:
        b = mess.pause(b, pause_b[0] * 1000, pause_b[1] * 1000)
        log["b_pause"] = {"start_ms": pause_b[0] * 1000, "duration_ms": pause_b[1] * 1000}

    feeds = out_dir / "feeds"
    keys = out_dir / "answer-keys"
    feeds.mkdir(parents=True, exist_ok=True)
    keys.mkdir(parents=True, exist_ok=True)
    _write_feed(feeds / "feed_a.jsonl", a, match_id)
    _write_feed(feeds / "feed_b.jsonl", b, match_id)

    key = {"match_id": match_id, "seed": seed, "mess_rules": sorted(rules),
           "clock_offset_ms": offset_ms, "events": truth.events, "mess_log": log,
           "players": truth.players, "frames_file": "frames_truth.npz"}
    (keys / "answer_key.json").write_text(json.dumps(key, indent=1))
    np.savez_compressed(keys / "frames_truth.npz",
                        **{f"{k}_{p}": _compact(getattr(fr, k)) for p, fr in truth.frames.items()
                           for k in ("ball", "pos", "codes")})
    return Fixture(feeds, keys, truth, offset_ms, log)
