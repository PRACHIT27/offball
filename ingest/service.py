"""Normalizer service: the logic behind the Azure Functions, with storage and publishing injected.

function_app.py only wires Azure SDK clients into this, so everything here runs in tests with
in-memory fakes.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from ingest.clean import NormalizedFrames, NormalizedMessage
from ingest.normalize import DeadLetter, Result, normalize_a, normalize_b
from ingest.teamsheet import TeamSheet


class SheetStore(Protocol):
    def load(self, match_id: str) -> str | None: ...
    def save(self, match_id: str, sheet_json: str) -> None: ...


class DeadLetterSink(Protocol):
    def write(self, path: str, record: dict) -> None: ...


# (body JSON, properties, partition key)
Publish = Callable[[list[tuple[str, dict, str]]], None]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def dead_letter_path(dl: DeadLetter) -> str:
    """`match_id/stage/time` as in LLD §8, plus a short hash so retries overwrite, not add."""
    digest = hashlib.sha256(f"{dl.feed}|{dl.body}".encode()).hexdigest()[:12]
    when = (dl.properties.get("emitted_at") or "unknown").replace(":", "-")
    return f"{dl.match_id or 'unknown'}/{dl.stage}/{when}-{digest}.json"


def _peek_match_id(body: str | bytes) -> str | None:
    """Fallback when a message arrives without the match_id property."""
    try:
        value = json.loads(body).get("matchId")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


class NormalizerService:
    def __init__(self, sheets: SheetStore, dead: DeadLetterSink, publish: Publish,
                 now: Callable[[], str] = utc_now) -> None:
        self.sheets = sheets
        self.dead = dead
        self.publish = publish
        self.now = now
        # Per-instance cache; the blob store is shared between instances
        self.cache: dict[str, TeamSheet] = {}

    def _sheet(self, match_id: str | None, need_lineup: bool) -> TeamSheet | None:
        if not match_id:
            return None
        sheet = self.cache.get(match_id)
        if sheet is None or (need_lineup and not sheet.has_lineup):
            stored = self.sheets.load(match_id)
            if stored:
                sheet = self.cache[match_id] = TeamSheet.model_validate_json(stored)
        return sheet

    def handle_batch(self, feed: str, messages: list[tuple[str | bytes, dict]]) -> dict:
        """Normalize one trigger batch from a raw hub; returns counts for logging."""
        out: list[tuple[str, dict, str]] = []
        counts = {"in": len(messages), "out": 0, "dead_letters": 0}
        for body, props in messages:
            result = self._one(feed, body, props)
            for msg in result.outputs:
                out.append(self._envelope(msg, props))
            for dl in result.dead_letters:
                self.dead.write(dead_letter_path(dl), dl.to_dict())
            counts["dead_letters"] += len(result.dead_letters)
        if out:
            self.publish(out)
        counts["out"] = len(out)
        return counts

    def _one(self, feed: str, body: str | bytes, props: dict) -> Result:
        match_id = props.get("match_id") or _peek_match_id(body)
        if match_id and not props.get("match_id"):
            props = {**props, "match_id": match_id}
        if feed == "A":
            result = normalize_a(body, props, self._sheet(match_id, need_lineup=True), self.now())
            if result.teamsheet is not None:
                self.cache[result.teamsheet.match_id] = result.teamsheet
                self.sheets.save(result.teamsheet.match_id, result.teamsheet.model_dump_json())
            return result
        return normalize_b(body, props, self._sheet(match_id, need_lineup=False), self.now())

    @staticmethod
    def _envelope(msg: NormalizedMessage, props: dict) -> tuple[str, dict, str]:
        match_id = msg.batch.match_id if isinstance(msg, NormalizedFrames) else (
            msg.event.match_id if msg.kind == "event" else msg.match_id)
        headers = {"emitted_at": props.get("emitted_at", ""), "feed": props.get("feed", ""),
                   "match_id": match_id, "kind": msg.kind}
        return msg.model_dump_json(), headers, match_id
