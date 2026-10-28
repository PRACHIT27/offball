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


CONTEXT = {"length_m": ("team length", 1, 1), "width_m": ("team width", 1, 1),
           "long_ball_share": ("long-ball share", 100, 0),
           "avg_pass_length_m": ("pass length", 1, 1),
           "control_share": ("control share", 100, 0), "offside_traps": ("offside traps", 1, 0)}
MEANING = {
    ("line_height_m", "down"): "sits deeper: less space in behind, invites the opponent on, "
                               "looks to counter",
    ("line_height_m", "up"): "holds a higher line: squeezes the pitch and wins the ball higher, "
                             "but leaves more space in behind",
    ("pressing_per_min", "up"): "hunts the ball higher up the pitch, trying to force mistakes",
    ("pressing_per_min", "down"): "sits off and lets the opponent have the ball, saving energy "
                                  "and protecting the space behind",
    ("length_m", "down"): "more compact: less room between the lines",
    ("length_m", "up"): "more stretched: gaps open between defence and midfield",
    ("long_ball_share", "up"): "goes longer and more direct",
    ("long_ball_share", "down"): "plays shorter, building through midfield",
    ("formation_out", "changed"): "changes shape without the ball",
}


def zone(x: float, y: float, home: bool) -> str:
    """A pitch position in words, from the team's own point of view (home attacks x = 105)."""
    d = x if home else 105 - x
    third = "defence" if d < 35 else "midfield" if d < 70 else "attack"
    channel = "wide" if y < 18 or y > 50 else "central"
    return f"{channel} {third}"


def situation(team: str, score: dict, home: str) -> str:
    mine, theirs = (score["home"], score["away"]) if team == home else (score["away"],
                                                                         score["home"])
    return "leading" if mine > theirs else "trailing" if mine < theirs else "level"


def _context(data: MatchData, team: str, window_ids: list[str]) -> dict:
    ws = [w for w in (data.window(i) for i in window_ids) if w and w.get("team_id") == team]
    if len(ws) < 2:
        return {}
    a, b = ws[0]["values"], ws[-1]["values"]
    out = {}
    for key, (label, scale, digits) in CONTEXT.items():
        if a.get(key) is None or b.get(key) is None:
            continue
        before, after = round(a[key] * scale, digits), round(b[key] * scale, digits)
        if digits == 0:
            before, after = int(before), int(after)
        out[label] = {"before": before, "after": after,
                      "unit": "%" if scale == 100 else "m" if key.endswith("_m") else ""}
    return out


def _meanings(changes: list[dict], context: dict) -> list[str]:
    out = []
    for c in changes:
        d = "changed" if c["measure"] == "formation_out" else c.get("direction")
        if (c["measure"], d) in MEANING:
            out.append(MEANING[(c["measure"], d)])
    length = context.get("team length")
    if length and abs(length["after"] - length["before"]) >= 4:
        out.append(MEANING[("length_m", "down" if length["after"] < length["before"] else "up")])
    longb = context.get("long-ball share")
    if longb and abs(longb["after"] - longb["before"]) >= 10:
        out.append(MEANING[("long_ball_share",
                            "up" if longb["after"] > longb["before"] else "down")])
    return out


OFF_BALL_WINDOW_MS = 300_000


def _totals_at(data: MatchData, t: int) -> dict:
    row = None
    for r in data.totals:
        if r["t"] > t:
            break
        row = r
    return (row or {}).get("players", {})


def off_ball(data: MatchData, play_ms: int) -> dict:
    """The last 5 minutes off the ball, per club, from Performance Metrics: decoy runs, free men
    who weren't found, who covered the most ground, sprints, top speed, passing."""
    lo = play_ms - OFF_BALL_WINDOW_MS
    recent = [c for c in data.cues if lo <= c["t"] <= play_ms]
    clubs = {data.home: {}, data.away: {}}
    team_of = lambda pid: (pid or "").split("-")[0]  # noqa: E731
    name = data.player_name

    runs: dict[str, dict] = {}
    for c in recent:
        if c["kind"] != "decoy_run":
            continue
        d = c["data"]
        r = runs.setdefault(d["runner_id"], {"runs": 0, "freed": set(), "pulled": 0})
        r["runs"] += 1
        r["pulled"] += len(d.get("pulled", []))
        if d.get("receiver_id"):
            r["freed"].add(name(d["receiver_id"]))
    free: dict[str, int] = {}
    missed: dict[str, int] = {}
    for c in recent:
        if c["kind"] != "best_option":
            continue
        d = c["data"]
        best = d.get("best") or {}
        if best.get("open") and best.get("player_id") != d.get("chosen_id"):
            free[best["player_id"]] = free.get(best["player_id"], 0) + 1
            club = team_of(d.get("passer_id"))
            missed[club] = missed.get(club, 0) + 1
    fast: dict[str, float] = {}
    for c in recent:
        if c["kind"] == "speed_alert" and c["data"].get("type") == "fast":
            pid = c["data"]["player_id"]
            fast[pid] = max(fast.get(pid, 0), c["data"]["speed_kmh"])

    now, then = _totals_at(data, play_ms), _totals_at(data, lo)
    for club, out in clubs.items():
        mine = [p for p in now if team_of(p) == club]
        club_runs = sorted(((p, r) for p, r in runs.items() if team_of(p) == club),
                           key=lambda x: -x[1]["runs"])
        if club_runs:
            out["decoy_runs"] = sum(r["runs"] for _, r in club_runs)
            out["top_decoy_runners"] = [
                {"player": name(p), "runs": r["runs"], "defenders_pulled": r["pulled"],
                 "freed": sorted(r["freed"])[:2]} for p, r in club_runs[:2]]
        club_free = sorted(((p, n) for p, n in free.items() if team_of(p) == club),
                           key=lambda x: -x[1])
        if club_free:
            out["free_man_not_found"] = missed.get(club, 0)
            out["most_often_free"] = [{"player": name(p), "times": n} for p, n in club_free[:2]]
        club_fast = sorted(((p, v) for p, v in fast.items() if team_of(p) == club),
                           key=lambda x: -x[1])
        if club_fast:
            out["fastest_run"] = {"player": name(club_fast[0][0]),
                                  "kmh": round(club_fast[0][1], 1)}
        if mine and then:
            ground = sorted(((p, (now[p].get("distance_m") or 0)
                              - ((then.get(p) or {}).get("distance_m") or 0)) for p in mine),
                            key=lambda x: -x[1])
            out["most_ground_5_min"] = [{"player": name(p), "metres": int(round(m))}
                                        for p, m in ground[:2] if m > 0]
            sprints = sorted(((p, (now[p].get("sprints") or 0)
                               - ((then.get(p) or {}).get("sprints") or 0)) for p in mine),
                             key=lambda x: -x[1])
            if sprints and sprints[0][1] > 0:
                out["most_sprints_5_min"] = {"player": name(sprints[0][0]),
                                             "sprints": int(sprints[0][1])}
            def stat(p, row, key):
                return (row.get(p) or {}).get(key) or 0

            def done(p, row):
                return stat(p, row, "passes") * stat(p, row, "pass_accuracy")

            tried = sum(stat(p, now, "passes") - stat(p, then, "passes") for p in mine)
            made = sum(done(p, now) - done(p, then) for p in mine)
            if tried >= 10:
                out["passes_5_min"] = {"tried": int(tried),
                                       "completed_pct": int(round(100 * made / tried))}
        if mine:
            top_xg = max(mine, key=lambda p: now[p].get("xg") or 0)
            if (now[top_xg].get("xg") or 0) >= 0.1:
                out["biggest_threat_so_far"] = {"player": name(top_xg),
                                                "xg": round(now[top_xg]["xg"], 2)}
    return {c: v for c, v in clubs.items() if v}


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
            pl = data.player(n.get("player_id")) if n else None
            if pl:
                f["player_role"] = pl.get("position")
            home = team == data.home
            b, a = before.get(key), after.get(key)
            f["change"] = {"measure": "player_position",
                           "from_zone": zone(*b, home) if b else None,
                           "to_zone": zone(*a, home) if a else None}
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
        if ev.get("previous"):  # the last check-in, so "pressing rose" can be checked
            f["previous"] = {t: _team_state(v) for t, v in ev["previous"].items()
                             if isinstance(v, dict)}

    if team:
        f["situation"] = situation(team, f["score"], data.home)
        ctx = _context(data, team, ev.get("window_ids", []))
        if ctx:
            f["context"] = ctx
        changes = f.get("changes") or ([f["change"]] if f.get("change") else [])
        meaning = _meanings(changes, ctx)
        if meaning:
            f["meaning"] = meaning

    if data.cues or data.totals:
        ob = off_ball(data, trigger["play_ms"])
        if ob:
            f["off_ball"] = {data.club_name(c): v for c, v in ob.items()}

    dw = ev.get("did_it_work")
    if dw:
        tilt = [dw["before"].get("field_tilt"), dw["after"].get("field_tilt")]
        f["did_it_work"] = {
            "xg_against_per_10_minutes": [dw["before"].get("xg_against_per10"),
                                          dw["after"].get("xg_against_per10")],
            "field_tilt_pct": [round(100 * t) for t in tilt] if None not in tilt else None,
            "xg_per_10_minutes": [dw["before"].get("xg_for_per10"),
                                  dw["after"].get("xg_for_per10")],
            "possession_pct": [round(100 * dw["before"]["possession_share"]),
                               round(100 * dw["after"]["possession_share"])]
            if dw["before"].get("possession_share") is not None
            and dw["after"].get("possession_share") is not None else None}
    return f
