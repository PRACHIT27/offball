import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ingest.clean import FRAME_MS, PERIOD_BASE_MS
from sim.engine import Truth, simulate
from sim.feeds import feed_a, feed_b
from sim.storyline import Storyline
from tests.fixturegen import mess
from tests.fixturegen.generate import _write_feed
from tests.fixturegen.providers import Clock


@dataclass
class MatchFiles:
    out_dir: Path
    feeds_dir: Path
    answer_key_dir: Path
    truth: Truth
    clock_offset_ms: int
    mess_log: dict


def write_frames(path: Path, truth: Truth) -> None:
    cols: dict[str, list] = {"period": [], "frame": [], "match_clock_ms": [],
                             "ball_x": [], "ball_y": [], "ball_z": []}
    for i in range(22):
        cols[f"p{i}_id"], cols[f"p{i}_x"], cols[f"p{i}_y"] = [], [], []
    tables = []
    for period, fr in truth.frames.items():
        n = len(fr.ball)
        data = {
            "period": np.full(n, period, dtype=np.int8),
            "frame": np.arange(n, dtype=np.int32),
            "match_clock_ms": PERIOD_BASE_MS[period] + np.arange(n, dtype=np.int64) * FRAME_MS,
            "ball_x": fr.ball[:, 0].astype(np.float32),
            "ball_y": fr.ball[:, 1].astype(np.float32),
            "ball_z": fr.ball[:, 2].astype(np.float32),
        }
        names = np.array(truth.players + [""])
        for i in range(22):
            data[f"p{i}_id"] = names[fr.codes[:, i]]
            data[f"p{i}_x"] = fr.pos[:, i, 0].astype(np.float32)
            data[f"p{i}_y"] = fr.pos[:, i, 1].astype(np.float32)
        tables.append(pa.table(data))
    pq.write_table(pa.concat_tables(tables), path, compression="zstd")


def generate(story: Storyline, out_dir: Path, mess_level: str = "light",
             period_s=(2790.0, 2880.0), halftime_s: float = 900.0) -> MatchFiles:
    rules = mess.LEVELS[mess_level]
    rng = np.random.default_rng(story.seed + 1)
    truth = simulate(story, period_s)
    clock = Clock(truth.period_length_ms(1), int(halftime_s * 1000))
    offset_ms = int(rng.integers(500, 2001)) if "a_clock_offset" in rules else 0
    log: dict = {}
    a = mess.apply_feed_a(rules, feed_a(truth, clock, offset_ms), truth, rng, log)
    b = mess.apply_feed_b(rules, feed_b(truth, clock, rng, 10.0 if "b_noise" in rules else 0.0),
                          rng, log)

    feeds = out_dir / "feeds"
    keys = out_dir / "answer-keys"
    match_dir = out_dir / "match"
    for d in (feeds, keys, match_dir):
        d.mkdir(parents=True, exist_ok=True)
    _write_feed(feeds / "feed_a.jsonl", a, truth.match_id)
    _write_feed(feeds / "feed_b.jsonl", b, truth.match_id)

    (match_dir / "match.json").write_text(json.dumps({
        "schema_version": "0.1", "match_id": truth.match_id, "storyline": truth.storyline,
        "seed": truth.seed, "home": truth.home, "away": truth.away,
        "pitch": {"length_m": 105, "width_m": 68}, "kickoff_team": truth.home,
        "score": truth.score}, indent=1))
    (match_dir / "prematch.json").write_text(json.dumps(truth.prematch, indent=1))
    with (match_dir / "events.jsonl").open("w") as f:
        for ev in truth.events:
            f.write(json.dumps(ev, separators=(",", ":")) + "\n")
    write_frames(match_dir / "frames.parquet", truth)

    key = {"match_id": truth.match_id, "storyline": truth.storyline, "seed": truth.seed,
           "home": truth.home, "away": truth.away, "score": truth.score,
           "mess_rules": sorted(rules), "clock_offset_ms": offset_ms,
           "tactic_changes": truth.tactic_changes,
           "true_player_stats": truth.true_player_stats,
           "events": truth.events, "mess_log": log, "players": truth.players,
           "frames_file": "frames_truth.npz"}
    (keys / "answer_key.json").write_text(json.dumps(key, indent=1))
    arrays = {}
    for p, fr in truth.frames.items():
        for k in ("ball", "pos", "codes", "possession"):
            a = getattr(fr, k)
            arrays[f"{k}_{p}"] = a.astype(np.float32) if a.dtype == np.float64 else a
    np.savez_compressed(keys / "frames_truth.npz", **arrays)
    return MatchFiles(out_dir, feeds, keys, truth, offset_ms, log)
