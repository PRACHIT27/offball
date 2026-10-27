"""Number-only cues (PM-22): created on air, versioned when their data changes, withdrawn when
their evidence goes (Broadcast LLD §5).

Cues tied to an event use the key `{event_id}:{kind}[:{detail}]`, so a correction finds them.
"""

from engine.metrics.models import Cue, CueKind, Evidence
from ingest.clean import Point

DURATION_MS: dict[str, int] = {
    "speed_alert": 4_000, "distance_milestone": 5_000, "pass_arc": 2_000, "shot_speed": 4_000,
    "xg_summary": 10_000, "decoy_run": 4_000, "best_option": 3_000,
}


def _point(anchor) -> Point | None:
    return Point(x=round(float(anchor[0]), 2), y=round(float(anchor[1]), 2)) if anchor else None


class CueBook:
    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.next_no = 1
        self.cues: dict[str, Cue] = {}
        self.by_key: dict[str, str] = {}

    def new(self, kind: CueKind, period: int, clock_ms: int, data: dict, evidence: Evidence,
            anchor=None) -> Cue:
        cue = Cue(cue_id=f"cue-{self.next_no:04d}", match_id=self.match_id, period=period,
                  kind=kind, start_clock_ms=clock_ms, duration_ms=DURATION_MS[kind],
                  anchor=_point(anchor), data=data, evidence=evidence)
        self.next_no += 1
        self.cues[cue.cue_id] = cue
        return cue

    def upsert(self, key: str, kind: CueKind, period: int, clock_ms: int, data: dict,
               evidence: Evidence, anchor=None) -> Cue | None:
        """Create the cue for `key`, or its next version if anything changed (else None)."""
        cue_id = self.by_key.get(key)
        if cue_id is None:
            cue = self.new(kind, period, clock_ms, data, evidence, anchor)
            self.by_key[key] = cue.cue_id
            return cue
        old = self.cues[cue_id]
        update = {"start_clock_ms": clock_ms, "period": period, "data": data,
                  "evidence": evidence, "anchor": _point(anchor), "status": "on_air",
                  "reason": None}
        if all(getattr(old, k) == v for k, v in update.items()):
            return None
        return self._put(old.model_copy(update=update | {"version": old.version + 1}))

    def withdraw(self, key: str, reason: str = "correction") -> Cue | None:
        cue_id = self.by_key.get(key)
        old = self.cues.get(cue_id) if cue_id else None
        if old is None or old.status == "withdrawn":
            return None
        return self._put(old.model_copy(update={"version": old.version + 1,
                                                "status": "withdrawn", "reason": reason}))

    def keys_for_event(self, event_id: str) -> list[str]:
        return [k for k in self.by_key if k.startswith(f"{event_id}:")]

    def get(self, key: str) -> Cue | None:
        cue_id = self.by_key.get(key)
        return self.cues.get(cue_id) if cue_id else None

    def _put(self, cue: Cue) -> Cue:
        self.cues[cue.cue_id] = cue
        return cue

    def to_state(self) -> dict:
        return {"next_no": self.next_no, "by_key": self.by_key,
                "cues": {k: c.model_dump(mode="json") for k, c in self.cues.items()}}

    @classmethod
    def from_state(cls, match_id: str, state: dict) -> "CueBook":
        b = cls(match_id)
        b.next_no, b.by_key = state["next_no"], state["by_key"]
        b.cues = {k: Cue.model_validate(c) for k, c in state["cues"].items()}
        return b
