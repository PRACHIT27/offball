"""Facts for one trigger: every number a caption about it may use, nothing else (IG-3, IG-22).

Templates write captions from these facts alone; agents start from them, and the checker accepts
a number only if it is in the facts or in a tool result from the same run.
"""

from engine.tactics.config import TacticsConfig
from insights.data import MatchData, minute_label

INSIGHT_KIND = {"crux": "expect", "shift": "shift", "external": "external",
                "check_in": "check_in", "summary": "summary"}
MEASURES = ("line_height_m", "pressing_per_min", "formation_out", "style_dial")
_CFG = TacticsConfig.load()


def changed(key: str, before, after) -> bool:
    """Same thresholds Tactical Intelligence uses to call a change."""
    if before is None or after is None:
        return False
    if key == "line_height_m":
        return abs(after - before) >= _CFG.line_height_m
    if key == "pressing_per_min":
        return (abs(after - before) >= _CFG.pressing_min_abs
                and abs(after - before) >= _CFG.pressing_pct / 100 * max(before, 0.1))
    if key == "style_dial":
        return abs(after - before) >= _CFG.style_points
    if key == "formation_out":
        return before != after
    return False


def _change(key: str, before, after) -> dict:
    c = {"measure": key, "before": before, "after": after}
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        c["direction"] = "up" if after > before else "down" if after < before else "same"
    return c


def _event(e: dict, data: MatchData) -> dict:
    return {"type": e["type"], "outcome": e["outcome"], "team": e["team_id"],
            "team_name": data.club_name(e["team_id"]), "player": data.player_name(e["player_id"]),
            "minute": minute_label(e["period"], e["match_clock_ms"])}


def _team_state(values: dict) -> dict:
    return {k: values.get(k) for k in MEASURES if values.get(k) is not None}


def build(trigger: dict, data: MatchData) -> dict:
    ev = trigger["evidence"]
    period, clock = trigger["period"], trigger["at_ms"]
    as_of = (period, clock)
    team = trigger.get("team_id")
    score = data.score(as_of)
    f = {
        "trigger_id": trigger["trigger_id"],
        "trigger_type": trigger["type"],
        "reason": trigger["reason"],
        "kind": INSIGHT_KIND.get(trigger["type"], trigger["type"]),
        "period": period,
        "at_ms": clock,
        "play_ms": trigger["play_ms"],
        "minute": minute_label(period, clock),
        "home": data.home, "away": data.away,
        "home_name": data.club_name(data.home), "away_name": data.club_name(data.away),
        "score": {"home": score[data.home], "away": score[data.away]},
        "team": team,
        "team_name": data.club_name(team) if team else None,
        "unusual": bool(ev.get("unusual")),
        "evidence": {"event_ids": list(ev.get("event_ids", [])),
                     "window_ids": list(ev.get("window_ids", []))},
    }
    if team:
        f["other"] = data.other(team)
        f["other_name"] = data.club_name(f["other"])

    events = [data.events[e] for e in ev.get("event_ids", []) if e in data.events]
    if trigger["type"] == "crux" and events:
        e = events[0]
        f["event"] = _event(e, data)
        if e["type"] in ("sub_on", "sub_off"):
            pair = [x for x in data.active_events(as_of) if x["type"] in ("sub_on", "sub_off")
                    and x["team_id"] == e["team_id"]
                    and abs(x["match_clock_ms"] - e["match_clock_ms"]) <= 2000]
            for x in pair:
                f["event"]["player_on" if x["type"] == "sub_on" else "player_off"] = \
                    data.player_name(x["player_id"])
        f["state"] = _team_state(ev.get("before") or {})
    if trigger["type"] == "external" and events and events[0]["type"] == "conditions":
        f["conditions"] = events[0].get("details") or {}

    before, after = ev.get("before") or {}, ev.get("after") or {}
    if trigger["type"] == "shift":
        key = next(iter(after), None)
        if key == "player_position":
            n = data.note(ev.get("note_id"))
            f["player"] = data.player_name(n.get("player_id")) if n else None
            f["change"] = {"measure": "player_position", "before": before.get(key),
                           "after": after.get(key)}
        elif key:
            f["change"] = _change(key, before.get(key), after.get(key))
        if ev.get("since_ms") is not None:
            f["since"] = minute_label(period if ev["since_ms"] >= 2_700_000 or period == 1 else 1,
                                      ev["since_ms"])
    if trigger["type"] == "confirm_due":
        changes = [_change(k, before.get(k), after.get(k)) for k in MEASURES
                   if changed(k, before.get(k), after.get(k))]
        f["kind"] = "confirmed" if changes else "retracted"
        f["changes"] = changes
        f["unchanged"] = [_change(k, before.get(k), after.get(k)) for k in
                          ("line_height_m", "pressing_per_min")
                          if before.get(k) is not None and after.get(k) is not None
                          and not changed(k, before.get(k), after.get(k))]
        crux = ev.get("crux_reason")
        f["crux_reason"] = crux
        crux_trig = next((t for t in data.triggers
                          if t["trigger_id"] == ev.get("crux_trigger_id")), None)
        if crux_trig:
            f["crux_minute"] = minute_label(crux_trig["period"], crux_trig["at_ms"])
            crux_events = [data.events[e] for e in crux_trig["evidence"].get("event_ids", [])
                           if e in data.events]
            if crux_events:  # who scored or was sent off, so nobody has to guess
                f["crux_event"] = _event(crux_events[0], data)
    if trigger["type"] == "summary":
        f["state"] = _team_state(after)
    if trigger["type"] in ("check_in", "external") and team is None and after:
        f["teams"] = {t: _team_state(v) for t, v in after.items() if isinstance(v, dict)}

    dw = ev.get("did_it_work")
    if dw:
        f["did_it_work"] = {
            "xg_per_10_minutes": [dw["before"].get("xg_for_per10"), dw["after"].get("xg_for_per10")],
            "possession_pct": [round(100 * dw["before"]["possession_share"]),
                               round(100 * dw["after"]["possession_share"])]
            if dw["before"].get("possession_share") is not None
            and dw["after"].get("possession_share") is not None else None}
    return f
