"""Build a replay file for the viewer screen: one simulated match run through ingestion,
Performance Metrics and Tactical Intelligence, exactly as the live engine would.

    python scripts/build_replay.py --storyline red_card --out web/public/replays
    python scripts/build_replay.py --feeds local_feeds/m001/feeds --match m001

Every number in the file comes from the engine's own outputs (stats, cues, tactics); nothing is
read from the answer key. Positions are kept at 5 per second (one per frame batch), in whole
decimetres with -1 for "not on the pitch"; the screen interpolates between them. Speeds are kept
once a second.
"""

import argparse
import json
import math
import tempfile
from pathlib import Path

from engine.local import run
from engine.merge.outputs import EventDelete, EventUpsert, Prematch
from engine.metrics.models import Cue, StatsMessage
from engine.metrics.router import MetricsEngine
from engine.tactics.engine import TacticsEngine
from ingest.clean import PERIOD_BASE_MS

TIMELINE_TYPES = {"shot", "card", "sub_on", "sub_off", "period_start", "period_end",
                  "conditions", "stoppage_start"}
CUE_KINDS = {"pass_arc", "speed_alert", "shot_speed", "best_option", "decoy_run",
             "distance_milestone"}


def dm(v) -> int:
    """Metres → whole decimetres; -1 when missing."""
    return -1 if v is None or (isinstance(v, float) and math.isnan(v)) else round(v * 10)


class Builder:
    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.prematch: dict = {}
        self.order: list[str] = []
        self.col: dict[str, int] = {}
        self.frames: list[list] = []  # [period, clock, ball_x, ball_y, [x, y, …] in dm]
        self.speeds: list[list] = []  # [period, clock, [km/h, …]] once a second
        self.cues: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.xg: list[dict] = []
        self.totals: list[dict] = []
        self.tactics: list[dict] = []
        self.note_player: dict[str, str | None] = {}
        self.period_end: dict[int, int] = {}

    def column(self, pid: str) -> int:
        if pid not in self.col:
            self.col[pid] = len(self.order)
            self.order.append(pid)
        return self.col[pid]

    def merge_output(self, msg) -> None:
        match msg:
            case Prematch():
                self.prematch = msg.prematch
            case EventUpsert() | EventDelete():
                ev = msg.event
                prev = self.events.get(ev.event_id)
                if prev is None or ev.version >= prev["version"]:
                    self.events[ev.event_id] = {
                        "id": ev.event_id, "version": ev.version, "status": ev.status,
                        "type": ev.type, "period": ev.period, "clock": ev.match_clock_ms,
                        "team": ev.team_id, "player": ev.player_id, "outcome": ev.outcome,
                        "target": ev.target_player_id}

    def metric(self, r) -> None:
        if isinstance(r, Cue):
            if r.kind in CUE_KINDS:
                self.cues[r.cue_id] = r.model_dump(mode="json")
            return
        if not isinstance(r, StatsMessage):
            return
        if r.kind == "positions":
            # Columns only for players who ever take the field, so the bench costs nothing
            f = r.values["frames"][-1]
            for pid in f["players"]:
                self.column(pid)
            pos = [-1] * (2 * len(self.order))
            for pid, (x, y) in f["players"].items():
                c = self.col[pid]
                pos[2 * c], pos[2 * c + 1] = dm(x), dm(y)
            clock = f["match_clock_ms"]
            self.frames.append([r.period, clock, dm(f["ball"][0]), dm(f["ball"][1]), pos])
            if not self.speeds or self.speeds[-1][0] != r.period or \
                    clock - self.speeds[-1][1] >= 1000:
                kmh = {pid: t["speed_kmh"] for pid, t in r.values["tags"].items()}
                self.speeds.append([r.period, clock,
                                    [round(kmh.get(pid) or 0) for pid in self.order]])
            self.period_end[r.period] = clock
        elif r.kind == "xg":
            self.xg.append({"period": r.period, "clock": r.match_clock_ms, "team": r.team_id,
                            **{k: r.values[k] for k in ("total_xg", "range", "shots",
                                                         "big_chances", "text")}})
        elif r.kind == "player_totals" and r.match_clock_ms % 60_000 < 10_000:
            self.totals.append({"period": r.period, "clock": r.match_clock_ms, "players": {
                pid: {k: v[k] for k in ("distance_m", "top_speed_ms", "sprints", "passes",
                                        "pass_accuracy", "xg")}
                for pid, v in r.values["players"].items() if v["frames_on"]}})

    def tactic(self, r: dict) -> None:
        if r.get("kind") == "note":
            self.note_player[r["note_id"]] = r.get("player_id")
        if r.get("sink") == "triggers":
            self.tactics.append({"kind": "trigger", **{k: r[k] for k in (
                "trigger_id", "type", "reason", "team_id", "importance", "at_ms", "period")},
                "player_id": self.note_player.get(r["evidence"].get("note_id")),
                "before": r["evidence"]["before"], "after": r["evidence"]["after"]})
        elif r["kind"] == "series":
            self.tactics.append({"kind": "series", "team_id": r["team_id"],
                                 "period": r["period"], "at_ms": r["at_ms"],
                                 "values": r["values"]})
        elif r["kind"] == "note" and r["level"] == "confirmed":
            self.tactics.append({"kind": "note", **{k: r.get(k) for k in (
                "note_id", "team_id", "change", "player_id", "before", "after", "at_ms",
                "period", "since_ms")}})
        elif r["kind"] == "window" and int(r["to_ms"]) % 60_000 < 10_000:
            v = r["values"]
            self.tactics.append({"kind": "window", "team_id": r["team_id"],
                                 "period": r["period"], "at_ms": r["to_ms"],
                                 "formation": v.get("formation_out"),
                                 "line_height_m": v.get("line_height_m"),
                                 "network": r["network"]})

    def build(self, storyline: str | None) -> dict:
        p1_end = self.period_end.get(1, PERIOD_BASE_MS[2])

        def t(period: int, clock: int) -> int:
            """One continuous play time across both halves (period 2's clock overlaps 1's)."""
            return clock if period == 1 else p1_end + (clock - PERIOD_BASE_MS[2])

        players = {}
        for side in ("home", "away"):
            for p in self.prematch[side]["players"]:
                players[p["player_id"]] = {"name": p["name"], "number": p["number"],
                                           "position": p["position"], "team": side}
        events = sorted((e for e in self.events.values()
                         if e["status"] == "active" and e["type"] in TIMELINE_TYPES),
                        key=lambda e: t(e["period"], e["clock"]))
        cues = sorted(({"t": t(c["period"], c["start_clock_ms"]), "id": c["cue_id"],
                        "kind": c["kind"], "duration_ms": c["duration_ms"], "data": c["data"],
                        "evidence": c["evidence"]}
                       for c in self.cues.values() if c["status"] == "on_air"),
                      key=lambda c: c["t"])
        return {
            "schema": "offball-replay/1",
            "match_id": self.match_id,
            "storyline": storyline,
            "home": {k: self.prematch["home"][k] for k in ("club_id", "name")},
            "away": {k: self.prematch["away"][k] for k in ("club_id", "name")},
            "managers": {s: (self.prematch[s].get("manager") or {}).get("name")
                         for s in ("home", "away")},
            "players": players,
            "order": self.order,
            "periods": {"1": {"t0": 0, "t1": p1_end},
                        "2": {"t0": p1_end, "t1": t(2, self.period_end.get(2, p1_end))}},
            "frames": [[t(p, c), p, c, bx, by, pos] for p, c, bx, by, pos in self.frames],
            "speeds": [[t(p, c), spd] for p, c, spd in self.speeds],
            "events": [{**e, "t": t(e["period"], e["clock"])} for e in events],
            "cues": cues,
            "xg": [{**x, "t": t(x["period"], x["clock"])} for x in self.xg],
            "totals": [{**x, "t": t(x["period"], x["clock"])} for x in self.totals],
            "tactics": [{**x, "t": t(int(x["period"]), int(x["at_ms"]))} for x in self.tactics],
        }


def build_replay(feeds: Path, match_id: str, storyline: str | None = None) -> dict:
    outputs, _ = run(feeds, match_id)
    b = Builder(match_id)
    metrics = MetricsEngine(match_id)
    tactics = TacticsEngine(match_id)
    for msg in outputs:
        b.merge_output(msg)
        for r in metrics.dispatch(msg):
            b.metric(r)
        for r in tactics.dispatch(msg):
            b.tactic(r)
    for r in metrics.flush():
        b.metric(r)
    for r in tactics.flush():
        b.tactic(r)
    return b.build(storyline)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a viewer-screen replay file")
    ap.add_argument("--storyline", help="simulate this storyline first (red_card, switch, …)")
    ap.add_argument("--feeds", type=Path, help="or use existing feed files")
    ap.add_argument("--match", help="match ID (with --feeds)")
    ap.add_argument("--minutes", type=float, default=None, help="period length for a short match")
    ap.add_argument("--out", type=Path, default=Path("web/public/replays"))
    args = ap.parse_args()

    if args.storyline:
        from sim.output import generate
        from sim.storyline import load

        story = load(args.storyline, None)
        tmp = Path(tempfile.mkdtemp(prefix="offball-replay-"))
        period_s = (args.minutes * 60, args.minutes * 60) if args.minutes else (2790.0, 2880.0)
        m = generate(story, tmp, "light", period_s=period_s)
        feeds, match_id = m.feeds_dir, m.truth.match_id
    else:
        feeds, match_id = args.feeds, args.match
    replay = build_replay(feeds, match_id, args.storyline)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{match_id}.json"
    path.write_text(json.dumps(replay, separators=(",", ":")))
    index = args.out / "index.json"
    matches = json.loads(index.read_text()) if index.exists() else []
    matches = [m for m in matches if m["match_id"] != match_id] + [{
        "match_id": match_id, "storyline": args.storyline,
        "title": f"{replay['home']['name']} v {replay['away']['name']}"}]
    index.write_text(json.dumps(sorted(matches, key=lambda m: m["match_id"]), indent=1))
    print(f"{path}: {path.stat().st_size / 1e6:.1f} MB, {len(replay['frames'])} frames, "
          f"{len(replay['cues'])} cues, {len(replay['events'])} events, "
          f"{len(replay['tactics'])} tactics items")


if __name__ == "__main__":
    main()
