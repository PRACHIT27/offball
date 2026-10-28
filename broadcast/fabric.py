"""Fabric Real-Time Intelligence sink (Platform PL-18).

Turns what the engine publishes on the `stats` and `triggers` hubs into rows for the Eventhouse
KQL database `offball`, and streams them in with a keyless token (Kusto streaming ingestion).
Used by scripts/fabric_load.py (a match from feed files) and, when FABRIC_KUSTO_URI is set, by
the cue manager (live). Only numbers the engine computed go in; nothing here derives new ones.

Built on by: the Real-Time Dashboard (scripts/fabric_dashboard.py).
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

log = logging.getLogger("broadcast.fabric")

DATABASE = "offball"
# One create-merge per table; scripts/fabric_dashboard.py runs them, so re-running is safe.
# Column names avoid Kusto keywords (kind, values, version).
SCHEMA = {
    "Matches": "match_id:string, storyline:string, home_id:string, home:string, away_id:string,"
               " away:string, kickoff:datetime",
    "Stats": "at:datetime, match_id:string, message:string, period:int, clock_ms:long,"
             " minute:real, team_id:string, player_id:string, data:dynamic",
    "Triggers": "at:datetime, match_id:string, trigger_id:string, type:string, reason:string,"
                " team_id:string, importance:real, period:int, clock_ms:long, minute:real,"
                " evidence:dynamic",
    "Cues": "at:datetime, match_id:string, cue_id:string, cue_kind:string, cue_version:int,"
            " status:string, reason:string, period:int, clock_ms:long, minute:real,"
            " caption_source:string",
    "Ingest": "at:datetime, match_id:string, minute:real, counts:dynamic, dead_letters:long",
    "Latency": "at:datetime, match_id:string, step:string, ms:real, minute:real",
}
# Large per-frame or per-window payloads the dashboard never reads
SLIM = {"positions": ("frames", "tags"), "window": ("network", "routes", "positions"),
        "territory": ("grid",)}


def iso(wall_ms: float) -> str:
    return datetime.fromtimestamp(wall_ms / 1000, UTC).isoformat()


def _minute(clock_ms) -> float | None:
    return None if clock_ms is None else round(clock_ms / 60_000, 3)


def match_row(match_id: str, prematch: dict, kickoff: str, storyline: str = "live") -> dict:
    home, away = prematch["home"], prematch["away"]
    return {"match_id": match_id, "storyline": storyline, "home_id": home["club_id"],
            "home": home["name"], "away_id": away["club_id"], "away": away["name"],
            "kickoff": kickoff}


def rows(at: str, body: dict, props: dict) -> list[tuple[str, dict]]:
    """One hub message as (table, row) pairs; [] for anything the dashboard doesn't use."""
    mid = body.get("match_id") or props.get("match_id")
    if props.get("type") == "cue" or "cue_id" in body:
        clock = body.get("start_clock_ms")
        return [("Cues", {"at": at, "match_id": mid, "cue_id": body["cue_id"],
                          "cue_kind": body.get("kind"), "cue_version": body.get("version", 1),
                          "status": body.get("status"), "reason": body.get("reason"),
                          "period": body.get("period"), "clock_ms": clock,
                          "minute": _minute(clock),
                          "caption_source": body.get("caption_source")})]
    if body.get("sink") == "triggers" or "trigger_id" in body:
        clock = body.get("at_ms")
        return [("Triggers", {"at": at, "match_id": mid, "trigger_id": body["trigger_id"],
                              "type": body.get("type"), "reason": body.get("reason"),
                              "team_id": body.get("team_id"),
                              "importance": body.get("importance"),
                              "period": body.get("period"), "clock_ms": clock,
                              "minute": _minute(clock), "evidence": body.get("evidence")})]
    kind = body.get("kind") or props.get("kind")
    if not kind:
        return []
    clock = body.get("match_clock_ms", body.get("at_ms", body.get("to_ms")))
    data = body.get("values") if "values" in body else {
        k: v for k, v in body.items() if k not in ("sink", "kind", "match_id", "team_id",
                                                   "period", "at_ms")}
    data = {k: v for k, v in (data or {}).items() if k not in SLIM.get(kind, ())}
    if kind == "window":
        data["unusual"] = body.get("unusual")
        data["window_id"] = body.get("window_id")
    return [("Stats", {"at": at, "match_id": mid, "message": kind, "period": body.get("period"),
                       "clock_ms": clock, "minute": _minute(clock),
                       "team_id": body.get("team_id"), "player_id": body.get("player_id"),
                       "data": data})]


class KustoSink:
    """Buffers rows per table and streams them to the Eventhouse every `every_s` seconds.

    Failures are logged and the batch dropped: the dashboard is monitoring, never on the path
    to the screen.
    """

    MAX_BYTES = 3_500_000  # streaming ingestion takes up to 4 MB per request

    def __init__(self, uri: str, credential, session, database: str = DATABASE,
                 every_s: float = 2.0) -> None:
        self.uri, self.credential, self.session = uri.rstrip("/"), credential, session
        self.database, self.every_s = database, every_s
        self.buffers: dict[str, list[str]] = {}
        self.sent = self.failed = 0

    def add(self, table: str, row: dict) -> None:
        self.buffers.setdefault(table, []).append(json.dumps(row, separators=(",", ":")))

    def extend(self, pairs: list[tuple[str, dict]]) -> None:
        for table, row in pairs:
            self.add(table, row)

    async def _token(self) -> str:
        return (await self.credential.get_token(f"{self.uri}/.default")).token

    async def command(self, csl: str) -> dict:
        async with self.session.post(
                f"{self.uri}/v1/rest/mgmt", json={"db": self.database, "csl": csl},
                headers={"Authorization": f"Bearer {await self._token()}"}) as r:
            if r.status >= 300:
                raise RuntimeError(f"{csl[:60]}: {r.status} {(await r.text())[:300]}")
            return await r.json()

    async def ensure_tables(self) -> None:
        for table, columns in SCHEMA.items():
            await self.command(f".create-merge table {table} ({columns})")

    async def flush(self) -> None:
        buffers, self.buffers = self.buffers, {}
        for table, lines in buffers.items():
            chunk, size = [], 0
            for line in lines + [None]:
                if line is None or size + len(line) > self.MAX_BYTES:
                    if chunk:
                        await self._post(table, chunk)
                    chunk, size = [], 0
                if line is not None:
                    chunk.append(line)
                    size += len(line) + 1

    async def _post(self, table: str, lines: list[str]) -> None:
        url = f"{self.uri}/v1/rest/ingest/{self.database}/{table}?streamFormat=MultiJSON"
        try:
            async with self.session.post(url, data="\n".join(lines).encode(), headers={
                    "Authorization": f"Bearer {await self._token()}",
                    "Content-Type": "application/json"}) as r:
                if r.status >= 300:
                    raise RuntimeError(f"{r.status} {(await r.text())[:200]}")
            self.sent += len(lines)
        except Exception as e:  # monitoring must never stop the match
            self.failed += len(lines)
            log.warning("fabric ingest to %s failed (%d rows): %s", table, len(lines), e)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.every_s)
            await self.flush()
