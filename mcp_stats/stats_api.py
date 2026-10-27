"""Stats API: read-only questions about a match, answered from Tactical Intelligence's windows and
the clean events, never with data after `as_of` (IG-6). Every answer lists the window or event IDs
it came from, so the checker and the viewer can trace each number.

Times are match minutes (clock / 60 000: the second half starts at 45). `as_of` is the
(period, match_clock_ms) of the trigger being explained.
"""

from collections import Counter
from statistics import mean

from insights.data import MatchData, at_or_before, minute_label

MEASURES = {
    "line_height": ("line_height_m", "length_m", "width_m", "offside_traps"),
    "pressing": ("pressing_per_min", "press_size", "ppda", "recovery_s"),
    "style": ("style_dial", "tempo_epm", "avg_pass_length_m", "long_ball_share", "chaos",
              "control_share"),
}
COMPARE = ("line_height_m", "pressing_per_min", "press_size", "style_dial", "control_share",
           "chaos", "length_m", "width_m")
NORMAL_FROM_MIN, NORMAL_TO_MIN = 5.0, 15.0  # Tactical Intelligence's baseline span


class StatsAPI:
    def __init__(self, data: MatchData):
        self.data = data

    # ---------- helpers ----------

    def team_id(self, team: str) -> str:
        t = team.strip()
        for side in ("home", "away"):
            club = self.data.prematch[side]
            if t.upper() == club["club_id"] or t.lower() == club["name"].lower():
                return club["club_id"]
        raise ValueError(f"unknown team {team!r}; use {self.data.home} or {self.data.away}")

    def windows(self, team: str, from_min: float, to_min: float,
                as_of: tuple[int, int]) -> list[dict]:
        tid = self.team_id(team)
        return [w for w in self.data.windows
                if w["team_id"] == tid and at_or_before(w["period"], w["to_ms"], as_of)
                and from_min < w["to_ms"] / 60_000 <= to_min]  # adjacent spans never overlap

    @staticmethod
    def _avg(windows: list[dict], key: str):
        vals = [w["values"][key] for w in windows if isinstance(w["values"].get(key), (int, float))]
        if not vals:
            return None
        return round(mean(vals), 2)

    @staticmethod
    def _ids(windows: list[dict]) -> list[str]:
        """First and last window IDs: enough to trace the span without listing every 10 s."""
        if not windows:
            return []
        return sorted({windows[0]["window_id"], windows[-1]["window_id"]})

    def _summary(self, team: str, from_min: float, to_min: float, as_of, keys) -> dict:
        ws = self.windows(team, from_min, to_min, as_of)
        if not ws:
            return {"team": self.team_id(team), "from_minute": from_min, "to_minute": to_min,
                    "windows": 0, "note": "no data in that span (or it is after as_of)"}
        return {"team": self.team_id(team), "from_minute": from_min, "to_minute": to_min,
                **{k: self._avg(ws, k) for k in keys},
                "latest": {k: ws[-1]["values"].get(k) for k in keys},
                "windows": len(ws), "window_ids": self._ids(ws)}

    # ---------- tools (LLD §6) ----------

    def line_height(self, team, from_min, to_min, as_of):
        return self._summary(team, from_min, to_min, as_of, MEASURES["line_height"])

    def pressing(self, team, from_min, to_min, as_of):
        out = self._summary(team, from_min, to_min, as_of, MEASURES["pressing"])
        ws = self.windows(team, from_min, to_min, as_of)
        if ws:
            out["press_triggers"] = ws[-1]["values"].get("press_triggers") or {}
        return out

    def style(self, team, from_min, to_min, as_of):
        return self._summary(team, from_min, to_min, as_of, MEASURES["style"])

    def formation(self, team, from_min, to_min, as_of):
        ws = self.windows(team, from_min, to_min, as_of)
        if not ws:
            return {"team": self.team_id(team), "windows": 0, "note": "no data in that span"}
        def shape(k: str) -> Counter:
            return Counter(w["values"].get(k) for w in ws if w["values"].get(k))

        out_of, in_pos = shape("formation_out"), shape("formation_in")
        return {"team": self.team_id(team), "from_minute": from_min, "to_minute": to_min,
                "out_of_possession": out_of.most_common(1)[0][0] if out_of else None,
                "in_possession": in_pos.most_common(1)[0][0] if in_pos else None,
                "latest_out_of_possession": ws[-1]["values"].get("formation_out"),
                "windows": len(ws), "window_ids": self._ids(ws)}

    def compare_periods(self, team, a_from, a_to, b_from, b_to, as_of):
        a = self.windows(team, a_from, a_to, as_of)
        b = self.windows(team, b_from, b_to, as_of)
        measures = {}
        for k in COMPARE:
            va, vb = self._avg(a, k), self._avg(b, k)
            measures[k] = {"a": va, "b": vb,
                           "difference": round(vb - va, 2) if va is not None and vb is not None
                           else None}
        fa = self.formation(team, a_from, a_to, as_of)
        fb = self.formation(team, b_from, b_to, as_of)
        measures["formation_out"] = {"a": fa.get("out_of_possession"),
                                     "b": fb.get("out_of_possession")}
        return {"team": self.team_id(team), "a": [a_from, a_to], "b": [b_from, b_to],
                "measures": measures, "window_ids": self._ids(a) + self._ids(b)}

    def normal_style(self, team, as_of):
        out = self._summary(team, NORMAL_FROM_MIN, NORMAL_TO_MIN, as_of, COMPARE)
        out["note"] = (f"baseline = this team's own play from minute {NORMAL_FROM_MIN:g} to "
                       f"{NORMAL_TO_MIN:g} of this match")
        return out

    def passing_network(self, team, from_min, to_min, as_of, top: int = 5):
        ws = self.windows(team, from_min, to_min, as_of)
        if not ws:
            return {"team": self.team_id(team), "windows": 0, "note": "no data in that span"}
        net = ws[-1].get("network") or {}
        edges = sorted(net.get("edges", []), key=lambda e: (-e["passes"], -e["danger"]))[:top]
        name = self.data.player_name
        return {"team": self.team_id(team), "window_id": ws[-1]["window_id"],
                "top_links": [{"from": name(e["from"]), "to": name(e["to"]),
                               "passes": e["passes"], "danger": e["danger"]} for e in edges]}

    def chance_routes(self, team, from_min, to_min, as_of):
        ws = self.windows(team, from_min, to_min, as_of)
        if not ws:
            return {"team": self.team_id(team), "windows": 0, "note": "no data in that span"}
        r = ws[-1].get("routes") or {}
        players = sorted((r.get("players") or {}).items(), key=lambda kv: -kv[1])[:3]
        return {"team": self.team_id(team), "window_id": ws[-1]["window_id"],
                "chances": r.get("chances"), "lanes": r.get("lanes"),
                "players": [{"player": self.data.player_name(p), "involvements": n}
                            for p, n in players]}

    def recent_events(self, team, last_n, as_of):
        tid = self.team_id(team) if team else None
        keep = ("shot", "card", "sub_on", "sub_off", "conditions", "stoppage_start")
        evs = [e for e in self.data.active_events(as_of)
               if e["type"] in keep and (tid is None or e["team_id"] == tid)
               and not (e["type"] == "shot" and e["outcome"] != "goal")]
        return {"team": tid, "events": [
            {"event_id": e["event_id"], "type": "goal" if e["type"] == "shot" else e["type"],
             "minute": minute_label(e["period"], e["match_clock_ms"]),
             "team": e["team_id"], "player": self.data.player_name(e["player_id"]),
             "outcome": e["outcome"] if e["type"] == "card" else None}
            for e in evs[-max(1, min(last_n, 10)):]]}

    def match_state(self, as_of):
        score = self.data.score(as_of)
        cards = Counter((e["team_id"], e["outcome"]) for e in self.data.active_events(as_of)
                        if e["type"] == "card")
        conditions = next((e.get("details") for e in reversed(self.data.active_events(as_of))
                           if e["type"] == "conditions"), None)
        return {"minute": minute_label(*as_of), "period": as_of[0],
                "score": {self.data.home: score[self.data.home],
                          self.data.away: score[self.data.away]},
                "home": self.data.club_name(self.data.home),
                "away": self.data.club_name(self.data.away),
                "cards": {f"{t}_{c}": n for (t, c), n in cards.items()},
                "conditions": conditions}
