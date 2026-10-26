"""Normalizers A and B (ingestion LLD §6.1): one raw message in, clean messages out. Stateless.

The caller (Azure Function or local runner) caches the team sheet and passes it in; a prematch or
lineup message returns an updated sheet to cache.
"""

import json
from dataclasses import asdict, dataclass, field

from pydantic import ValidationError

from ingest.clean import (
    FRAME_MS,
    PERIOD_BASE_MS,
    CleanEvent,
    CleanFrame,
    CleanFrameBatch,
    NormalizedDelete,
    NormalizedEvent,
    NormalizedFrames,
    NormalizedMessage,
    NormalizedPrematch,
    PlayerPosition,
    Point,
    Point3,
)
from ingest.raw import (
    FeedADelete,
    FeedAEvent,
    FeedALineup,
    FeedAPrematch,
    FeedBBatch,
    feed_a_adapter,
)
from ingest.teamsheet import TeamSheet, UnknownId, from_prematch, with_lineup

TYPES = {1: "pass", 3: "take_on", 4: "foul", 7: "tackle", 8: "interception", 12: "clearance",
         17: "card", 18: "sub_off", 19: "sub_on", 30: "period_end", 32: "period_start",
         90: "conditions", 91: "stoppage_start", 92: "stoppage_end"}
SHOT_OUTCOMES = {13: "off_target", 14: "post", 15: "saved", 16: "goal"}
QUALIFIER_TAGS = {1: "long_ball", 2: "cross", 15: "header"}
Q_END_X, Q_END_Y, Q_RECEIVER, Q_CARD = 140, 141, 7, 31


class Unmappable(ValueError):
    """A provider type or payload with no place in our schema."""


@dataclass
class DeadLetter:
    feed: str
    stage: str
    reason: str
    body: str
    properties: dict
    match_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Result:
    outputs: list[NormalizedMessage] = field(default_factory=list)
    dead_letters: list[DeadLetter] = field(default_factory=list)
    # Set when the message changed the team sheet; the caller caches it
    teamsheet: TeamSheet | None = None


def _text(body: str | bytes) -> str:
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body


def _dead(feed: str, stage: str, err: Exception | str, body, props: dict) -> Result:
    return Result(dead_letters=[DeadLetter(feed, stage, str(err)[:500], _text(body), props,
                                           props.get("match_id"))])


def _metres(x: float, y: float, period: int) -> Point:
    """Feed A grid (absolute, teams switch ends at half) → metres with home attacking +x."""
    mx, my = x * 1.05, y * 0.68
    if period == 2:
        mx, my = 105 - mx, 68 - my
    return Point(x=round(mx, 2), y=round(my, 2))


def _timings(props: dict, now: str) -> dict[str, str]:
    return {"emitted_at": props.get("emitted_at", ""), "normalized_at": now}


# ---------- Feed A ----------


def _clean_event(msg: FeedAEvent, sheet: TeamSheet, props: dict, now: str) -> CleanEvent:
    if 13 <= msg.typeId <= 16:
        type_, outcome = "shot", SHOT_OUTCOMES[msg.typeId]
    elif msg.typeId in TYPES:
        type_, outcome = TYPES[msg.typeId], None
    else:
        raise Unmappable(f"unknown typeId {msg.typeId}")

    quals = {q.qualifierId: q.value for q in msg.qualifiers}
    if type_ == "pass" and msg.outcome is not None:
        outcome = "complete" if msg.outcome == 1 else "incomplete"
    elif type_ == "card":
        if quals.get(Q_CARD) not in ("yellow", "red"):
            raise Unmappable("card without colour qualifier 31")
        outcome = quals[Q_CARD]
    elif outcome is None and msg.outcome is not None:
        outcome = "success" if msg.outcome == 1 else "fail"

    details = None
    if type_ == "conditions":
        c = msg.conditions or {}
        try:
            details = {"weather": c["weather"], "temperature_c": c["temperatureC"],
                       "pitch": c["pitch"]}
        except KeyError as e:
            raise Unmappable(f"conditions missing {e}") from None
    elif type_ in ("stoppage_start", "stoppage_end"):
        if not msg.stoppageId:
            raise Unmappable("stoppage without stoppageId")
        details = {"stoppage_id": msg.stoppageId, "reason": msg.reason}

    end = target = None
    try:
        if Q_END_X in quals and Q_END_Y in quals:
            end = _metres(float(quals[Q_END_X]), float(quals[Q_END_Y]), msg.periodId)
        if Q_RECEIVER in quals:
            target = sheet.player_from_feed_a(int(quals[Q_RECEIVER]))[1]
    except ValueError as e:
        raise Unmappable(f"bad qualifier value: {e}") from None

    return CleanEvent(
        event_id=f"e-{msg.eventId:06d}",
        version=msg.version,
        match_id=msg.matchId,
        match_clock_ms=PERIOD_BASE_MS[msg.periodId] + round(msg.timeSec * 1000),
        period=msg.periodId,
        type=type_,
        team_id=sheet.team_from_feed_a(msg.teamId) if msg.teamId is not None else None,
        player_id=sheet.player_from_feed_a(msg.playerId)[1] if msg.playerId is not None else None,
        target_player_id=target,
        start=_metres(msg.x, msg.y, msg.periodId) if msg.x is not None and msg.y is not None
        else None,
        end=end,
        outcome=outcome,
        qualifiers=[QUALIFIER_TAGS[q] for q in quals if q in QUALIFIER_TAGS],
        provider_xg=msg.xG,
        details=details,
        source_ids={"feed_a": msg.eventId},
        emitted_at=props.get("emitted_at", ""),
        timings=_timings(props, now),
    )


def normalize_a(body: str | bytes, props: dict, sheet: TeamSheet | None, now: str) -> Result:
    try:
        raw = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return _dead("A", "parse", e, body, props)
    try:
        msg = feed_a_adapter.validate_python(raw)
    except ValidationError as e:
        return _dead("A", "validate", e, body, props)

    try:
        match msg:
            case FeedAPrematch():
                new = from_prematch(msg.prematch)
                return Result([NormalizedPrematch(match_id=msg.matchId,
                                                  prematch=msg.prematch.model_dump(),
                                                  emitted_at=props.get("emitted_at", ""))],
                              teamsheet=new)
            case FeedALineup():
                if sheet is None:
                    return _dead("A", "map_ids", "lineup before prematch team sheet", body, props)
                return Result(teamsheet=with_lineup(sheet, msg))
            case FeedADelete():
                return Result([NormalizedDelete(match_id=msg.matchId,
                                                event_id=f"e-{msg.eventId:06d}",
                                                version=msg.version, source_id=msg.eventId,
                                                emitted_at=props.get("emitted_at", ""),
                                                timings=_timings(props, now))])
            case FeedAEvent():
                if sheet is None or not sheet.has_lineup:
                    return _dead("A", "map_ids", "event before lineup", body, props)
                return Result([NormalizedEvent(event=_clean_event(msg, sheet, props, now))])
    except UnknownId as e:
        return _dead("A", "map_ids", e, body, props)
    except Unmappable as e:
        return _dead("A", "map_types", e, body, props)
    except ValidationError as e:
        return _dead("A", "convert", e, body, props)
    raise AssertionError("unreachable")


# ---------- Feed B ----------


def normalize_b(body: str | bytes, props: dict, sheet: TeamSheet | None, now: str) -> Result:
    try:
        raw = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return _dead("B", "parse", e, body, props)
    try:
        msg = FeedBBatch.model_validate(raw)
    except ValidationError as e:
        return _dead("B", "validate", e, body, props)
    if sheet is None:
        return _dead("B", "map_ids", "frames before prematch team sheet", body, props)

    base = PERIOD_BASE_MS[msg.periodId]
    sign = 1 if msg.periodId == 1 else -1  # teams switch ends at half-time
    shirts = sheet.feed_b_shirts()
    frames = []
    try:
        for fr in msg.frames:
            n = fr.frameIdx - msg.periodStartFrame
            if n < 0:
                raise Unmappable(f"frameIdx {fr.frameIdx} before period start")
            bx, by, bz = fr.ball
            players = []
            for side, rows in (("home", fr.home), ("away", fr.away)):
                for shirt, x, y in rows:
                    if (side, shirt) not in shirts:
                        raise UnknownId(f"feed B {side} shirt {shirt} not on team sheet")
                    # Values come from the validated raw batch, so skip re-validation
                    players.append(PlayerPosition.model_construct(
                        player_id=shirts[(side, shirt)], x=round(52.5 + sign * x / 100, 3),
                        y=round(34 + sign * y / 100, 3)))
            frames.append(CleanFrame(
                frame=n, match_clock_ms=base + n * FRAME_MS,
                ball=Point3(x=round(52.5 + sign * bx / 100, 3), y=round(34 + sign * by / 100, 3),
                            z=round(bz / 100, 3)),
                players=players))
    except UnknownId as e:
        return _dead("B", "map_ids", e, body, props)
    except Unmappable as e:
        return _dead("B", "convert", e, body, props)

    batch = CleanFrameBatch(match_id=msg.matchId, period=msg.periodId, frames=frames,
                            source_ids={"feed_b": msg.batchSeq},
                            emitted_at=props.get("emitted_at", ""), timings=_timings(props, now))
    return Result([NormalizedFrames(batch=batch)])
