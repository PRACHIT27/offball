"""Clean (Silver) format, Data Ingestion LLD §7. Everything after ingestion sees only this.

Published as JSON Schema in contracts/ingestion/ (python -m engine.contracts).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0
FRAME_MS = 40
PERIOD_BASE_MS = {1: 0, 2: 2_700_000}

EventId = Annotated[str, Field(pattern=r"^e-\d{6}$")]
Period = Literal[1, 2]
EventType = Literal[
    "pass",
    "take_on",
    "foul",
    "tackle",
    "interception",
    "clearance",
    "shot",
    "card",
    "sub_off",
    "sub_on",
    "period_start",
    "period_end",
    "conditions",
    "stoppage_start",
    "stoppage_end",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point(_Model):
    x: float
    y: float


class Point3(_Model):
    x: float
    y: float
    z: float


class CleanEvent(_Model):
    event_id: EventId
    version: Annotated[int, Field(ge=1)]
    status: Literal["active", "deleted"] = "active"
    match_id: str
    match_clock_ms: int
    period: Period
    type: EventType
    team_id: str | None = None
    player_id: str | None = None
    target_player_id: str | None = None
    start: Point | None = None
    end: Point | None = None
    outcome: str | None = None
    qualifiers: list[str] = []
    provider_xg: float | None = None
    # Conditions and stoppage payloads (weather, stoppage id and reason)
    details: dict | None = None
    source_ids: dict[str, int]
    emitted_at: str
    # Per-stage timestamps for delay measurement (FR-25)
    timings: dict[str, str] = {}


class PlayerPosition(_Model):
    player_id: str
    x: float
    y: float


class CleanFrame(_Model):
    # Frames since the start of the period (25 Hz)
    frame: Annotated[int, Field(ge=0)]
    match_clock_ms: int
    ball: Point3
    players: list[PlayerPosition]
    interpolated: bool = False


class CleanFrameBatch(_Model):
    match_id: str
    period: Period
    frames: list[CleanFrame]
    source_ids: dict[str, int] = {}
    emitted_at: str
    timings: dict[str, str] = {}


# ---------- Messages on the `normalized` hub (normalizer → merge stage) ----------


class NormalizedEvent(_Model):
    kind: Literal["event"] = "event"
    event: CleanEvent


class NormalizedDelete(_Model):
    kind: Literal["delete"] = "delete"
    match_id: str
    event_id: EventId
    version: int
    source_id: int
    emitted_at: str
    timings: dict[str, str] = {}


class NormalizedFrames(_Model):
    kind: Literal["frames"] = "frames"
    batch: CleanFrameBatch


class NormalizedPrematch(_Model):
    kind: Literal["prematch"] = "prematch"
    match_id: str
    prematch: dict
    emitted_at: str


NormalizedMessage = Annotated[
    NormalizedEvent | NormalizedDelete | NormalizedFrames | NormalizedPrematch,
    Field(discriminator="kind"),
]
