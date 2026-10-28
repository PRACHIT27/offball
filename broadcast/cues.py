"""Cue manager logic (Broadcast LLD §5–§7), with no I/O so it runs in tests.

One `MatchCues` per match. Messages from the `stats` hub and captions from Insight Generation go
in; envelopes for the browsers come out. Every cue keeps its newest version; a correction or a
producer pull makes a new version, and withdrawn cues stay in the log with their `reason`.

Time on the screen is `t`, ms of play since kick-off, continuous across both halves (period 2's
clock overlaps period 1's stoppage time), the same `t` as the recorded replays.
"""

import time
from collections import deque

PERIOD_2_BASE_MS = 2_700_000
POSITIONS_KEEP = 50  # 10 s of 200 ms batches, for late joiners
LOG_KEEP = 5_000
TACTICS_KINDS = ("series", "window", "note")
# Only the light stats travel to browsers; heatmaps are 35 KB each and the screen doesn't use them
STATS_KINDS = ("pass", "shot", "xg", "player_totals")


def insight_cue_id(insight_id: str) -> str:
    return f"ins-{insight_id}"


class MatchCues:
    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.p1_end: int | None = None
        self.prematch: dict | None = None
        self.positions: deque = deque(maxlen=POSITIONS_KEEP)
        self.cues: dict[str, dict] = {}
        self.insights: dict[str, dict] = {}
        self.history: dict[str, list] = {"stats": [], "tactics": []}
        self.log: deque = deque(maxlen=LOG_KEEP)
        self.counts = {"messages": 0, "cues": 0, "withdrawn": 0, "pulls": 0, "insights": 0}
        self.last_message_at: float | None = None
        self.last_t = 0

    # ---------- time ----------

    def t(self, period: int, clock_ms: int) -> int:
        if period == 1:
            self.p1_end = max(self.p1_end or 0, clock_ms)
            return clock_ms
        return (self.p1_end or PERIOD_2_BASE_MS) + (clock_ms - PERIOD_2_BASE_MS)

    # ---------- inputs ----------

    def on_stats(self, body: dict, props: dict, now: float | None = None) -> list[dict]:
        """One `stats` hub message: metrics (`type` stats or cue) or tactics (no `type`)."""
        self.counts["messages"] += 1
        self.last_message_at = now if now is not None else time.time()
        kind = body.get("kind")
        if props.get("type") == "cue" or "cue_id" in body:
            return self._cue(body, source="metrics")
        if kind == "positions":
            t = self.t(body["period"], body["match_clock_ms"])
            self.last_t = max(self.last_t, t)
            env = {"type": "positions", "t": t, "period": body["period"],
                   "frames": body["values"]["frames"], "tags": body["values"]["tags"],
                   "ball_speed_ms": body["values"].get("ball_speed_ms")}
            self.positions.append(env)
            return [env]
        if kind in STATS_KINDS:
            env = {"type": "stats", "t": self.t(body["period"], body["match_clock_ms"]),
                   "data": body}
            self.history["stats"].append(env)
            return [env]
        if kind in TACTICS_KINDS:
            if kind == "note" and body.get("level") != "confirmed":
                return []
            at = body.get("to_ms") if kind == "window" else body.get("at_ms")
            env = {"type": "tactics", "t": self.t(int(body["period"]), int(at)),
                   "data": _slim_tactics(body)}
            self.history["tactics"].append(env)
            return [env]
        return []

    def _cue(self, cue: dict, source: str) -> list[dict]:
        prev = self.cues.get(cue["cue_id"])
        if prev and prev["version"] > cue["version"]:
            return []  # an older version arriving late
        if prev and prev.get("reason") == "producer_pull" and cue.get("status") != "withdrawn":
            return []  # a pulled cue stays off air
        t = self.t(cue["period"], cue["start_clock_ms"])
        stored = {**cue, "t": t, "source": source}
        self.cues[cue["cue_id"]] = stored
        self.counts["cues"] += prev is None
        self.counts["withdrawn"] += cue.get("status") == "withdrawn"
        self._log("cue", stored)
        return [{"type": "cue", "cue": stored}]

    def add_insights(self, rows: list[dict]) -> list[dict]:
        """Captions from Insight Generation (`/api/insights` rows); each one becomes a cue."""
        out = []
        for row in rows:
            iid = row.get("insight_id")
            if not iid or iid in self.insights:
                continue
            self.insights[iid] = row
            self.counts["insights"] += 1
            cue = {"cue_id": insight_cue_id(iid), "version": 1, "kind": "insight",
                   "status": "on_air", "t": row["t"], "data": {"kind": row.get("kind")},
                   "captions": row.get("captions", {}),
                   "caption_source": row.get("caption_source"), "source": "insights",
                   "evidence": row.get("evidence", {}), "trigger_id": row.get("trigger_id")}
            self.cues[cue["cue_id"]] = cue
            self._log("insight", cue)
            out.append({"type": "insight", "data": row})
        return out

    # ---------- producer ----------

    def pull(self, cue_id: str, who: str = "producer") -> dict | None:
        """Withdraw a cue on air (Broadcast LLD §9). Returns the envelope, or None."""
        cue = self.cues.get(cue_id)
        if cue is None or cue.get("status") == "withdrawn":
            return None
        pulled = {**cue, "version": cue["version"] + 1, "status": "withdrawn",
                  "reason": "producer_pull", "pulled_by": who, "pulled_at": time.time()}
        self.cues[cue_id] = pulled
        self.counts["pulls"] += 1
        self.counts["withdrawn"] += 1
        self._log("pull", pulled)
        return {"type": "cue", "cue": pulled}

    # ---------- reads ----------

    def state(self) -> dict:
        """Everything a viewer joining late needs to draw the match up to now."""
        return {"match_id": self.match_id, "p1_end": self.p1_end, "last_t": self.last_t,
                "prematch": self.prematch, "positions": list(self.positions),
                "cues": list(self.cues.values()), "insights": list(self.insights.values()),
                "stats": self.history["stats"], "tactics": self.history["tactics"]}

    def summary(self) -> dict:
        return {"match_id": self.match_id, "last_t": self.last_t,
                "last_message_at": self.last_message_at, **self.counts,
                "home": (self.prematch or {}).get("home", {}).get("name"),
                "away": (self.prematch or {}).get("away", {}).get("name")}

    def _log(self, what: str, cue: dict) -> None:
        self.log.append({"at": time.time(), "what": what, "cue_id": cue["cue_id"],
                         "kind": cue.get("kind"), "version": cue.get("version"),
                         "status": cue.get("status"), "reason": cue.get("reason")})


def _slim_tactics(body: dict) -> dict:
    """What the screen draws from Tactical Intelligence (same fields as the replay files)."""
    kind = body["kind"]
    base = {"kind": kind, "team_id": body.get("team_id"), "period": int(body["period"])}
    if kind == "series":
        return {**base, "at_ms": body["at_ms"], "window_id": body.get("window_id"),
                "values": body["values"]}
    if kind == "window":
        v = body.get("values", {})
        return {**base, "at_ms": int(body["to_ms"]), "formation": v.get("formation_out"),
                "line_height_m": v.get("line_height_m"), "network": body.get("network")}
    return {**base, **{k: body.get(k) for k in ("note_id", "change", "player_id", "before",
                                               "after", "at_ms", "since_ms")}}
