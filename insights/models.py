"""Insight Generation outputs (LLD §11)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

InsightKind = Literal["expect", "confirmed", "retracted", "shift", "check_in", "summary",
                      "external"]


class Checker(BaseModel):
    attempts: int = 0
    passed: bool = True
    reasons: list[str] = []


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str
    trigger_id: str
    match_id: str
    kind: InsightKind
    period: int
    at_ms: int
    play_ms: int
    team_id: str | None = None
    text_en_core: str
    captions: dict[str, str]
    evidence: dict[str, list[str]]
    caption_source: Literal["agent", "template"]
    checker: Checker = Checker()
    latency_ms: int = 0
