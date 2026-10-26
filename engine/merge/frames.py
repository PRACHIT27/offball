"""Frame path of the merge stage (LLD §6.2): fix units, dedupe by frame number, fill short gaps."""

from ingest.clean import FRAME_MS, CleanFrame, CleanFrameBatch, PlayerPosition, Point3

MAX_FILL_FRAMES = 12  # ≤ 0.5 s at 25 Hz is interpolated; longer gaps are announced
HALF = (52.5, 34.0)
UNIT_FACTOR = 100
OFF_PITCH = 5.0  # positions this many half-pitches from the centre are a unit mistake


def _reach(batch: CleanFrameBatch) -> float:
    """How far the batch reaches from the centre, in half-pitch lengths (1.0 = touchline)."""
    worst = 0.0
    for f in batch.frames:
        for x, y in [(f.ball.x, f.ball.y), *((p.x, p.y) for p in f.players)]:
            worst = max(worst, abs(x - HALF[0]) / HALF[0], abs(y - HALF[1]) / HALF[1])
    return worst


def _rescale(batch: CleanFrameBatch) -> CleanFrameBatch:
    def fix(x: float, y: float) -> tuple[float, float]:
        return (round(HALF[0] + (x - HALF[0]) / UNIT_FACTOR, 3),
                round(HALF[1] + (y - HALF[1]) / UNIT_FACTOR, 3))

    frames = []
    for f in batch.frames:
        bx, by = fix(f.ball.x, f.ball.y)
        players = [PlayerPosition(player_id=p.player_id, x=fx, y=fy)
                   for p in f.players for fx, fy in [fix(p.x, p.y)]]
        frames.append(f.model_copy(update={"ball": f.ball.model_copy(update={"x": bx, "y": by}),
                                           "players": players}))
    return batch.model_copy(update={"frames": frames})


def fix_units(batch: CleanFrameBatch) -> tuple[CleanFrameBatch | None, dict]:
    """Rescale a batch sent in the wrong units (FR-16); reject it if rescaling doesn't help."""
    if _reach(batch) <= OFF_PITCH:
        return batch, {}
    fixed = _rescale(batch)
    if _reach(fixed) <= 1.2:
        return fixed, {"units_fixed": 1}
    return None, {"frames_rejected": len(batch.frames)}


def _lerp(a: float, b: float, s: float) -> float:
    return round(a + (b - a) * s, 3)


def interpolate(before: CleanFrame, after: CleanFrame) -> list[CleanFrame]:
    """Linear fill for the frames strictly between two frames, flagged interpolated (FR-15)."""
    n = after.frame - before.frame
    step_ms = (after.match_clock_ms - before.match_clock_ms) / n
    after_pos = {p.player_id: p for p in after.players}
    out = []
    for i in range(1, n):
        s = i / n
        out.append(CleanFrame(
            frame=before.frame + i,
            match_clock_ms=round(before.match_clock_ms + step_ms * i),
            ball=Point3(x=_lerp(before.ball.x, after.ball.x, s),
                        y=_lerp(before.ball.y, after.ball.y, s),
                        z=_lerp(before.ball.z, after.ball.z, s)),
            players=[PlayerPosition(player_id=p.player_id,
                                    x=_lerp(p.x, after_pos[p.player_id].x, s),
                                    y=_lerp(p.y, after_pos[p.player_id].y, s))
                     for p in before.players if p.player_id in after_pos],
            interpolated=True))
    return out


class FrameTrack:
    def __init__(self) -> None:
        # period → last frame handed on
        self.last: dict[int, CleanFrame] = {}

    def handle(self, batch: CleanFrameBatch) -> tuple[CleanFrameBatch | None, dict, list[dict]]:
        """Returns the batch to hand on (None if nothing new), counts, and gap notices."""
        batch, counts = fix_units(batch)
        if batch is None:
            return None, counts, []
        prev = self.last.get(batch.period)
        last_no = prev.frame if prev else -1
        fresh = [f for f in batch.frames if f.frame > last_no]
        counts["frames_duplicate"] = len(batch.frames) - len(fresh)
        if not fresh:
            return None, counts, []

        frames: list[CleanFrame] = []
        notices: list[dict] = []
        for f in fresh:
            missing = f.frame - (prev.frame if prev else -1) - 1
            if missing > MAX_FILL_FRAMES:
                detail = {"missing_frames": missing, "first_frame": f.frame - missing}
                notices += [
                    {"kind": "notice.gap_start", "frame": f.frame - missing,
                     "match_clock_ms": f.match_clock_ms - FRAME_MS * missing, "details": detail},
                    {"kind": "notice.gap_end", "frame": f.frame,
                     "match_clock_ms": f.match_clock_ms, "details": detail}]
                counts["gaps"] = counts.get("gaps", 0) + 1
            elif missing > 0 and prev is not None:
                filled = interpolate(prev, f)
                frames += filled
                counts["frames_interpolated"] = counts.get("frames_interpolated", 0) + len(filled)
            frames.append(f)
            prev = f
        self.last[batch.period] = prev
        return batch.model_copy(update={"frames": frames}), counts, notices

    def to_state(self) -> dict:
        return {"last": {p: f.model_dump() for p, f in self.last.items()}}

    @classmethod
    def from_state(cls, state: dict) -> "FrameTrack":
        t = cls()
        t.last = {int(p): CleanFrame.model_validate(f) for p, f in state["last"].items()}
        return t
