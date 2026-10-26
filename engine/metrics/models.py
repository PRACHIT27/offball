"""What Performance Metrics sends out (LLD §6, §7, HLD §6 cue v0.2).

These shapes are what other domains build on; engine/metrics/README.md lists who uses which.
They live here until the team agrees to publish them in contracts/.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ingest.clean import Point

CUE_SCHEMA_VERSION = "0.2"

StatsKind = Literal["positions", "player_totals", "heatmap", "pass", "shot", "xg"]
CueKind = Literal["speed_alert", "distance_milestone", "pass_arc", "shot_speed", "xg_summary",
                  "decoy_run", "best_option"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_Model):
    event_ids: list[str] = []
    frames: list[int] = []


class StatsMessage(_Model):
    """One message on the `stats` hub: the fast path to the screen.

    Built on by: the PubSub bridge and viewer screen (Broadcast, Audience), Fabric Eventstream.
    """

    kind: StatsKind
    match_id: str
    period: int
    match_clock_ms: int
    player_id: str | None = None
    team_id: str | None = None
    # Follows the event's version for pass and shot results; a consumer keeps the highest
    version: int = 1
    status: Literal["active", "deleted"] = "active"
    values: dict
    best_option: dict | None = None
    evidence: Evidence = Evidence()


class Cue(_Model):
    """Number-only overlay cue. Goes on air at once; no approval step (Broadcast LLD §5).

    Built on by: the cue manager and the browser cue player (Broadcast). Sent on `stats` with
    message property `type=cue`.
    """

    cue_id: str
    version: int = 1
    schema_version: str = CUE_SCHEMA_VERSION
    match_id: str
    period: int
    kind: CueKind
    start_clock_ms: int
    duration_ms: int
    anchor: Point | None = None
    data: dict
    evidence: Evidence
    captions: dict[str, str] = {}
    caption_source: Literal["none"] = "none"
    status: Literal["on_air", "withdrawn"] = "on_air"
    reason: Literal["correction", "producer_pull"] | None = None


class MetricDoc(_Model):
    """Snapshot for Cosmos `metrics` (partition `match_id`), read by the Stats API (LLD §7).

    Built on by: the Stats API / MCP server (Insight Generation). `player:` totals are cumulative,
    so a from…to range is a subtraction.
    """

    id: str
    match_id: str
    type: Literal["player_totals", "event_result"]
    period: int
    match_clock_ms: int
    body: dict


# ---------- direct calls to Tactical Intelligence (PM-26) ----------


class PressureSample(_Model):
    """Pressure on the ball carrier at one frame. TI counts a press at pressure ≥ 0.75.

    Built on by: Tactical Intelligence (pressing), by direct call. Shape awaits TI's OK.
    """

    kind: Literal["pressure"] = "pressure"
    match_id: str
    period: int
    match_clock_ms: int
    frame: int
    carrier_id: str
    team_id: str
    pressure: float
    presser_id: str | None


class PassValues(_Model):
    """Pitch-value gain of one pass, for the passing network and chance routes.

    Built on by: Tactical Intelligence, by direct call; re-sent on correction, `deleted` on
    deletion. Shape awaits TI's OK.
    """

    kind: Literal["pass_values"] = "pass_values"
    match_id: str
    period: int
    match_clock_ms: int
    event_id: str
    version: int
    status: Literal["active", "deleted"] = "active"
    team_id: str
    passer_id: str
    receiver_id: str | None
    completed: bool
    p_complete: float
    value_start: float
    value_end: float
    value_gain: float


MetricsOutput = StatsMessage | Cue | MetricDoc | PressureSample | PassValues
