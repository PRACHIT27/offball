"""What the merge stage hands to the router and the store (Data Ingestion LLD §6.2, §7)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ingest.clean import CleanEvent, CleanFrameBatch


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventUpsert(_Model):
    kind: Literal["event.upsert"] = "event.upsert"
    event: CleanEvent
    # Released after the wait window had already passed its match time (FR-13)
    late: bool = False


class EventDelete(_Model):
    kind: Literal["event.delete"] = "event.delete"
    event: CleanEvent


class FramesOut(_Model):
    kind: Literal["frames"] = "frames"
    batch: CleanFrameBatch


NoticeKind = Literal[
    "notice.gap_start",
    "notice.gap_end",
    "notice.feed_stopped",
    "notice.feed_resumed",
    "notice.correction_applied",
    "conditions.changed",
    "stoppage.start",
    "stoppage.end",
]


class Notice(_Model):
    kind: NoticeKind
    # Deterministic, so a replayed notice overwrites instead of doubling
    notice_id: str
    match_id: str
    period: int | None = None
    match_clock_ms: int | None = None
    details: dict = {}
    emitted_at: str


class Prematch(_Model):
    kind: Literal["prematch"] = "prematch"
    match_id: str
    prematch: dict


MergeOutput = Annotated[
    EventUpsert | EventDelete | FramesOut | Notice | Prematch, Field(discriminator="kind")
]
