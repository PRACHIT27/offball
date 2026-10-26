"""Raw provider wire formats (Data Ingestion LLD §13). Nothing outside ingest/ imports this."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

ClubId = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
PlayerId = Annotated[str, Field(pattern=r"^[A-Z]{3}-\d{2}$")]
Grid = Annotated[float, Field(ge=0, le=100)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- Pre-match (passed through feed A) ----------


class PrematchPlayer(BaseModel):
    model_config = ConfigDict(extra="allow")
    player_id: PlayerId
    number: Annotated[int, Field(ge=1, le=99)]
    name: str
    position: str
    starting: bool


class PrematchSide(BaseModel):
    model_config = ConfigDict(extra="allow")
    club_id: ClubId
    name: str
    players: Annotated[list[PrematchPlayer], Field(min_length=11)]


class Prematch(BaseModel):
    """Team sheets plus whatever else the simulator sends (clubs, managers, history)."""

    model_config = ConfigDict(extra="allow")
    match_id: str
    home: PrematchSide
    away: PrematchSide


# ---------- Feed A (event style) ----------


class Qualifier(_Strict):
    qualifierId: int
    value: str


class LineupPlayer(_Strict):
    playerId: int
    shirt: Annotated[int, Field(ge=1, le=99)]


class LineupTeam(_Strict):
    teamId: int
    side: Literal["home", "away"]
    players: Annotated[list[LineupPlayer], Field(min_length=11)]


class FeedAPrematch(_Strict):
    msgType: Literal["prematch"]
    matchId: str
    prematch: Prematch


class FeedALineup(_Strict):
    msgType: Literal["lineup"]
    matchId: str
    teams: Annotated[list[LineupTeam], Field(min_length=2, max_length=2)]


class FeedAEvent(_Strict):
    msgType: Literal["event"]
    matchId: str
    eventId: Annotated[int, Field(ge=1, le=999_999)]
    version: Annotated[int, Field(ge=1)]
    typeId: int
    periodId: Literal[1, 2]
    timeSec: Annotated[float, Field(ge=0)]
    teamId: int | None = None
    playerId: int | None = None
    outcome: Literal[0, 1] | None = None
    x: Grid | None = None
    y: Grid | None = None
    qualifiers: list[Qualifier] = []
    xG: Annotated[float, Field(ge=0, le=1)] | None = None
    conditions: dict | None = None
    stoppageId: str | None = None
    reason: str | None = None


class FeedADelete(_Strict):
    msgType: Literal["delete"]
    matchId: str
    eventId: Annotated[int, Field(ge=1, le=999_999)]
    version: Annotated[int, Field(ge=1)]


FeedAMessage = Annotated[
    FeedAPrematch | FeedALineup | FeedAEvent | FeedADelete, Field(discriminator="msgType")
]
feed_a_adapter: TypeAdapter[FeedAMessage] = TypeAdapter(FeedAMessage)


# ---------- Feed B (tracking style) ----------

# [shirt, x_cm, y_cm]
PlayerCm = tuple[Annotated[int, Field(ge=1, le=99)], float, float]


class FeedBFrame(_Strict):
    frameIdx: Annotated[int, Field(ge=0)]
    ball: tuple[float, float, float]
    home: list[PlayerCm]
    away: list[PlayerCm]


class FeedBBatch(_Strict):
    msgType: Literal["frames"]
    matchId: str
    batchSeq: Annotated[int, Field(ge=0)]
    periodId: Literal[1, 2]
    periodStartFrame: Annotated[int, Field(ge=0)]
    frames: Annotated[list[FeedBFrame], Field(min_length=1)]
