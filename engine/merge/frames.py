"""Frame path of the merge stage: dedupe by frame number (LLD §6.2)."""

from ingest.clean import CleanFrameBatch


class FrameTrack:
    def __init__(self) -> None:
        # period → last frame number handed on
        self.last: dict[int, int] = {}

    def handle(self, batch: CleanFrameBatch) -> tuple[CleanFrameBatch | None, dict]:
        """Returns the batch with duplicate frames removed (None if nothing new) and counts."""
        last = self.last.get(batch.period, -1)
        fresh = [f for f in batch.frames if f.frame > last]
        counts = {"frames_duplicate": len(batch.frames) - len(fresh)}
        if not fresh:
            return None, counts
        self.last[batch.period] = fresh[-1].frame
        return batch.model_copy(update={"frames": fresh}), counts

    def to_state(self) -> dict:
        return {"last": self.last}

    @classmethod
    def from_state(cls, state: dict) -> "FrameTrack":
        t = cls()
        t.last = {int(k): v for k, v in state["last"].items()}
        return t
