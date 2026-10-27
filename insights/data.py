"""What Insight Generation knows about a match: pre-match info, clean events and Tactical
Intelligence's windows, notes and triggers. Locally it is loaded from files; the Stats API
(mcp_stats) serves the same data to the agents with an as_of cut-off.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.merge.outputs import EventDelete, EventUpsert, Prematch

PERIOD_BASE_MS = {1: 0, 2: 2_700_000}
PERIOD_MINUTES = {1: 45, 2: 90}


def minute_label(period: int, clock_ms: int) -> str:
    """Broadcast minute: 15:00 → 15', stoppage time 46:10 in the first half → 45+2'."""
    base = PERIOD_MINUTES[period]
    if clock_ms > base * 60_000:
        return f"{base}+{-(-(clock_ms - base * 60_000) // 60_000)}'"
    return f"{clock_ms // 60_000}'"


def at_or_before(period: int, clock_ms: int, as_of: tuple[int, int]) -> bool:
    return (period, clock_ms) <= as_of


@dataclass
class MatchData:
    match_id: str
    prematch: dict = field(default_factory=dict)
    events: dict[str, dict] = field(default_factory=dict)  # latest version per event_id
    windows: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)

    # ---------- building ----------

    def add_merge_output(self, msg) -> None:
        match msg:
            case Prematch():
                self.prematch = msg.prematch
            case EventUpsert() | EventDelete():
                ev = msg.event
                prev = self.events.get(ev.event_id)
                if prev is None or ev.version >= prev["version"]:
                    self.events[ev.event_id] = ev.model_dump(
                        mode="json", exclude={"timings", "source_ids", "emitted_at"})

    def add_tactics(self, r: dict) -> None:
        if r.get("sink") == "triggers":
            self.triggers.append(r)
        elif r.get("kind") == "window":
            self.windows.append(r)
        elif r.get("kind") == "note":
            self.notes.append(r)

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prematch.json").write_text(json.dumps(self.prematch))
        for name, rows in (("events", self.events.values()), ("windows", self.windows),
                           ("notes", self.notes), ("triggers", self.triggers)):
            with (folder / f"{name}.jsonl").open("w") as f:
                for r in rows:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")

    @classmethod
    def load(cls, folder: Path, match_id: str) -> "MatchData":
        def rows(name):
            p = folder / f"{name}.jsonl"
            return [json.loads(line) for line in p.open()] if p.exists() else []
        d = cls(match_id, json.loads((folder / "prematch.json").read_text()))
        d.events = {e["event_id"]: e for e in rows("events")}
        d.windows, d.notes, d.triggers = rows("windows"), rows("notes"), rows("triggers")
        return d

    # ---------- lookups ----------

    @property
    def home(self) -> str:
        return self.prematch["home"]["club_id"]

    @property
    def away(self) -> str:
        return self.prematch["away"]["club_id"]

    def club_name(self, club_id: str | None) -> str:
        for side in ("home", "away"):
            if self.prematch[side]["club_id"] == club_id:
                return self.prematch[side]["name"]
        return club_id or ""

    def other(self, club_id: str) -> str:
        return self.away if club_id == self.home else self.home

    def player(self, player_id: str | None) -> dict | None:
        for side in ("home", "away"):
            for p in self.prematch[side]["players"]:
                if p["player_id"] == player_id:
                    return p
        return None

    def player_name(self, player_id: str | None) -> str:
        p = self.player(player_id)
        return p["name"] if p else (player_id or "")

    def active_events(self, as_of: tuple[int, int]) -> list[dict]:
        return sorted((e for e in self.events.values() if e["status"] == "active"
                       and at_or_before(e["period"], e["match_clock_ms"], as_of)),
                      key=lambda e: (e["period"], e["match_clock_ms"]))

    def score(self, as_of: tuple[int, int]) -> dict[str, int]:
        score = {self.home: 0, self.away: 0}
        for e in self.active_events(as_of):
            if e["type"] == "shot" and e["outcome"] == "goal" and e["team_id"] in score:
                score[e["team_id"]] += 1
        return score

    def note(self, note_id: str | None) -> dict | None:
        return next((n for n in self.notes if n["note_id"] == note_id), None)

    def window(self, window_id: str) -> dict | None:
        return next((w for w in self.windows if w["window_id"] == window_id), None)
