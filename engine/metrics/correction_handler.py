"""Correction handler (PM-25): a new version or a deletion of an event recomputes its result,
fixes the running totals, and updates or withdraws its cues."""

from engine.metrics.event_processor import EventProcessor, Snapshot
from engine.metrics.models import MetricsOutput
from ingest.clean import CleanEvent


class CorrectionHandler:
    def __init__(self, events: EventProcessor) -> None:
        self.events = events

    def upsert(self, ev: CleanEvent) -> list[MetricsOutput]:
        ep = self.events
        prev = ep.ledger.get(ev.event_id)
        if prev is None:
            # Not computed yet (new, or still waiting for frames): the newest version wins
            ep.pending = [p for p in ep.pending if p.event_id != ev.event_id]
            return ep.submit(ev)
        if prev.event.version >= ev.version:
            return []
        if ep.memory.nearest_index(ev.period, ev.match_clock_ms) is not None:
            snap = ep.snapshot(ev)
        else:
            # Frames have rolled out of memory: reuse what the first computation saw
            snap = Snapshot(**prev.snapshot.to_state())
            if snap.decoy_receiver != ev.target_player_id:
                snap.decoy_receiver, snap.decoys = None, []
        return ep.apply(ev, snap)

    def delete(self, ev: CleanEvent) -> list[MetricsOutput]:
        ep = self.events
        ep.pending = [p for p in ep.pending if p.event_id != ev.event_id]
        return ep.apply(ev, Snapshot())
