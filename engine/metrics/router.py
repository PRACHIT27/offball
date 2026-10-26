"""Router (LLD §4): the merge stage hands every clean message here by direct call; nothing polls.

    for clean in merge.handle(raw):
        for result in router.dispatch(clean):
            publisher.emit(result)
"""

from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, MergeOutput, Prematch
from engine.metrics.correction_handler import CorrectionHandler
from engine.metrics.cues import CueBook
from engine.metrics.event_processor import HANDLED, EventProcessor
from engine.metrics.frame_processor import FrameProcessor
from engine.metrics.memory import FrameMemory, Roster
from engine.metrics.models import MetricsOutput
from engine.metrics.totals import Totals


class MetricsEngine:
    """Performance Metrics for one match. `to_state` / `from_state` snapshot it for restarts;
    the 10 s frame memory is not saved and refills from the replayed frames."""

    def __init__(self, match_id: str, roster: Roster | None = None, totals: Totals | None = None,
                 cues: CueBook | None = None) -> None:
        self.match_id = match_id
        self.roster = roster or Roster()
        self.totals = totals or Totals()
        self.cues = cues or CueBook(match_id)
        self.memory = FrameMemory(self.roster)
        self.frames = FrameProcessor(match_id, self.roster, self.memory, self.totals, self.cues)
        self.events = EventProcessor(match_id, self.roster, self.memory, self.totals, self.cues)
        self.corrections = CorrectionHandler(self.events)

    def dispatch(self, msg: MergeOutput) -> list[MetricsOutput]:
        match msg:
            case Prematch():
                self._prematch(msg.prematch)
                return []
            case FramesOut():
                return self.frames.process(msg.batch) + self.events.release_ready()
            case EventUpsert():
                ev = msg.event
                if ev.type in HANDLED or ev.event_id in self.events.ledger:
                    return self.corrections.upsert(ev)
                return []
            case EventDelete():
                return self.corrections.delete(msg.event)
        return []

    def flush(self) -> list[MetricsOutput]:
        """End of the feed: compute whatever is still waiting for frames, and final totals."""
        ep, out = self.events, []
        for ev in list(ep.pending):
            out += ep.apply(ev, ep.snapshot(ev))
        ep.pending = []
        m = self.memory
        if m.smoothed_to >= 0:
            s = m.slot(m.smoothed_to)
            out += self.frames.snapshot(m.period, int(m.clock[s]), int(m.frame[s]))
        return out

    def _prematch(self, prematch: dict) -> None:
        home = prematch.get("home") or {}
        self.roster.home_id = home.get("club_id") or self.roster.home_id
        # Fixed columns for every listed player, so state and snapshots line up
        for side in ("home", "away"):
            for p in (prematch.get(side) or {}).get("players", []):
                self.roster.column(p["player_id"])

    def to_state(self) -> dict:
        return {"match_id": self.match_id, "roster": self.roster.to_state(),
                "totals": self.totals.to_state(), "cues": self.cues.to_state(),
                "events": self.events.to_state(),
                "frames": {"match_top": self.frames.match_top,
                           "last_top_alert_ms": self.frames.last_top_alert_ms,
                           "totals_bucket": self.frames.totals_bucket}}

    @classmethod
    def from_state(cls, state: dict) -> "MetricsEngine":
        e = cls(state["match_id"], Roster.from_state(state["roster"]),
                Totals.from_state(state["totals"]),
                CueBook.from_state(state["match_id"], state["cues"]))
        e.events.load_state(state["events"])
        f = state["frames"]
        e.frames.match_top = f["match_top"]
        e.frames.last_top_alert_ms = f["last_top_alert_ms"]
        e.frames.totals_bucket = tuple(f["totals_bucket"]) if f["totals_bucket"] else None
        return e
