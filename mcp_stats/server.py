"""MCP stats server (LLD §6): the only way agents get numbers (IG-4).

Every tool takes `as_of_period` and `as_of_clock_ms` and never returns data after that moment
(IG-6). Inside OffBall the agent workflow overwrites both on every call with the trigger's time,
so a model can't ask about the future; other MCP clients (GitHub Copilot, VS Code, Claude Desktop)
pass them themselves.

    OFFBALL_MATCH_DATA=local_out/m001/insights/data OFFBALL_MATCH=m001 python -m mcp_stats.server
"""

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from insights.data import MatchData
from mcp_stats.stats_api import StatsAPI

mcp = MCPServer("offball-stats", instructions=(
    "Football match statistics for one simulated match. Times are match minutes (the second "
    "half starts at 45). Teams are club IDs or names. Every answer lists the window or event "
    "IDs it came from."))
_api: StatsAPI | None = None
_loaded_at = 0.0


def api() -> StatsAPI:
    """The match data, reloaded whenever the live service writes a newer snapshot."""
    global _api, _loaded_at
    folder = Path(os.environ.get("OFFBALL_MATCH_DATA", "local_out/m001/insights/data"))
    changed = max((p.stat().st_mtime for p in folder.glob("*")), default=0.0)
    if _api is None or changed > _loaded_at:
        _api = StatsAPI(MatchData.load(folder, os.environ.get("OFFBALL_MATCH",
                                                              folder.parent.parent.name)))
        _loaded_at = changed
    return _api


def _as_of(period: int, clock_ms: int) -> tuple[int, int]:
    return (int(period), int(clock_ms))


@mcp.tool()
def get_line_height(team: str, from_minute: float, to_minute: float,
                    as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """Defensive line height (m from own goal), team length and width, offside traps."""
    return api().line_height(team, from_minute, to_minute, _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_pressing(team: str, from_minute: float, to_minute: float,
                 as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """Pressing intensity (presses per minute), press size, PPDA, recovery time, press triggers."""
    return api().pressing(team, from_minute, to_minute, _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_style(team: str, from_minute: float, to_minute: float,
              as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """Style dial (0 = patient short passing, 100 = direct long balls), tempo (events per
    minute), average pass length, long-ball share, control share (share of time on the ball,
    0–1) and chaos (0 calm – 100 frantic: turnovers, short possessions, unstable shape)."""
    return api().style(team, from_minute, to_minute, _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_formation(team: str, from_minute: float, to_minute: float,
                  as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """Shape in and out of possession over a span (most common) and the latest one."""
    return api().formation(team, from_minute, to_minute, _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def compare_periods(team: str, a_from_minute: float, a_to_minute: float, b_from_minute: float,
                    b_to_minute: float, as_of_period: int = 2,
                    as_of_clock_ms: int = 10_000_000) -> dict:
    """Every measure for span A and span B, with the difference (B − A)."""
    return api().compare_periods(team, a_from_minute, a_to_minute, b_from_minute, b_to_minute,
                                 _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_normal_style(team: str, as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """The team's normal level for each measure (its own minutes 5–15 of this match)."""
    return api().normal_style(team, _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_passing_network(team: str, from_minute: float, to_minute: float,
                        as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """The most used passing links and how dangerous they are (latest window in the span)."""
    return api().passing_network(team, from_minute, to_minute,
                                 _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_chance_routes(team: str, from_minute: float, to_minute: float,
                      as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """Where chances come from (left, centre, right) and who is involved (latest window)."""
    return api().chance_routes(team, from_minute, to_minute, _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_recent_events(team: str = "", last_n: int = 5, as_of_period: int = 2,
                      as_of_clock_ms: int = 10_000_000) -> dict:
    """Latest goals, cards, substitutions and condition changes (optionally for one team)."""
    return api().recent_events(team or None, last_n, _as_of(as_of_period, as_of_clock_ms))


@mcp.tool()
def get_match_state(as_of_period: int = 2, as_of_clock_ms: int = 10_000_000) -> dict:
    """Score, minute, cards and conditions at the given moment."""
    return api().match_state(_as_of(as_of_period, as_of_clock_ms))


if __name__ == "__main__":
    mcp.run()
