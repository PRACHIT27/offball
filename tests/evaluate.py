"""Score cleaned output against a fixture's answer key (FR-26). Evaluation only: the live path
never imports this or reads answer-keys/."""

import json
from dataclasses import dataclass
from pathlib import Path

from engine.merge.outputs import EventDelete, EventUpsert

CLOCK_TOL_MS = 80
POS_TOL_M = 0.5


def answer_key(answer_key_dir: Path) -> dict:
    return json.loads((answer_key_dir / "answer_key.json").read_text())


def final_events(outputs) -> dict:
    """Latest version per event, as a consumer keeping the highest version would see it."""
    latest = {}
    for o in outputs:
        if isinstance(o, EventUpsert | EventDelete):
            ev = o.event
            if ev.event_id not in latest or ev.version >= latest[ev.event_id].version:
                latest[ev.event_id] = ev
    return latest


def _same(ev, t) -> bool:
    if (ev.type, ev.team_id, ev.player_id, ev.target_player_id, ev.outcome, ev.period) != (
            t["type"], t["team_id"], t["player_id"], t["target_player_id"], t["outcome"],
            t["period"]):
        return False
    if abs(ev.match_clock_ms - t["match_clock_ms"]) > CLOCK_TOL_MS:
        return False
    for key in ("start", "end"):
        if t[key]:
            p = getattr(ev, key)
            if p is None or max(abs(p.x - t[key]["x"]), abs(p.y - t[key]["y"])) > POS_TOL_M:
                return False
    return True


@dataclass
class Score:
    recovered: int
    true_total: int
    extra_active: list[str]
    missing: list[str]

    @property
    def recovery(self) -> float:
        return self.recovered / self.true_total


def score(outputs, key: dict) -> Score:
    latest = final_events(outputs)
    truth = {t["event_id"]: t for t in key["events"]}
    missing = [i for i, t in truth.items()
               if i not in latest or latest[i].status != "active" or not _same(latest[i], t)]
    extra = [i for i, ev in latest.items() if i not in truth and ev.status == "active"]
    return Score(len(truth) - len(missing), len(truth), extra, missing)


def score_store(store, key: dict) -> Score:
    """Score what a run stored (all versions) instead of its in-memory outputs."""
    from ingest.clean import CleanEvent

    events = [EventUpsert(event=CleanEvent.model_validate(d)) for d in store.events.values()]
    return score(events, key)
