from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, MergeOutput, Notice, Prematch
from engine.tactics.config import TacticsConfig
from engine.tactics.detector import ChangeDetector, Promoter, Snapshot
from engine.tactics.measures import WindowCalc
from engine.tactics.state import MatchState, depth
from engine.tactics.triggers import TriggerBuffer, importance
from ingest.clean import PERIOD_BASE_MS, CleanEvent

SERIES_KEYS = ("line_height_m", "pressing_per_min", "control_share", "chaos", "style_dial")


def mmss(ms: int) -> str:
    s = max(ms, 0) // 1000
    return f"{s // 60:02d}{s % 60:02d}"


class TacticsEngine:
    def __init__(self, match_id: str, cfg: TacticsConfig | None = None):
        self.match_id = match_id
        self.cfg = cfg or TacticsConfig.load()
        self.state = MatchState(self.cfg.sample_every_frames)
        self.detector = ChangeDetector(self.cfg)
        self.promoter = Promoter(self.cfg)
        self.buffer = TriggerBuffer(self.cfg)
        self.next_mark: dict[int, int] = {}
        self.p1_end = PERIOD_BASE_MS[2]
        self.score: dict[str, int] = {}
        self.next_trigger = 1
        self.check_ins_done: set[int] = set()
        self.late_done = False
        self.pending_confirm: list[dict] = []
        self.latest: dict[str, Snapshot] = {}
        self.stoppages: dict[str, int] = {}
        self.ready = False
        self.recent_formations: dict[str, list] = {}
        self.formation: dict[str, str | None] = {}

    def play_ms(self, period: int, clock: int) -> int:
        return clock if period == 1 else self.p1_end + (clock - PERIOD_BASE_MS[2])

    def minute(self, period: int, clock: int) -> float:
        return clock / 60000

    def dispatch(self, msg: MergeOutput) -> list[dict]:
        match msg:
            case Prematch():
                self.state.roster.load_prematch(msg.prematch)
                r = self.state.roster
                self.score = {r.home: 0, r.away: 0}
                self.ready = True
                return []
            case FramesOut():
                if not self.ready:
                    return []
                period = msg.batch.period
                if period == 2 and self.state.clock_ms[1] > 0:
                    self.p1_end = self.state.clock_ms[1]
                self.state.add_frames(msg.batch)
                return self.advance(period)
            case EventUpsert():
                return self.on_event(msg.event) if self.ready else []
            case EventDelete():
                self.state.delete(msg.event)
                return []
            case Notice():
                return []
        return []

    def advance(self, period: int) -> list[dict]:
        out: list[dict] = []
        clock = self.state.clock_ms[period]
        start = PERIOD_BASE_MS[period]
        step = int(self.cfg.refresh_s * 1000)
        mark = self.next_mark.get(period, start + step)
        grace = int(self.cfg.event_grace_s * 1000)
        while clock - grace >= mark:
            out += self.compute_windows(period, mark)
            mark += step
        self.next_mark[period] = mark
        return out

    def compute_windows(self, period: int, t1: int) -> list[dict]:
        out: list[dict] = []
        t0 = max(PERIOD_BASE_MS[period], t1 - int(self.cfg.window_s * 1000))
        win = self.state.window(period, t0, t1)
        if win is None:
            return out
        r = self.state.roster
        play = self.play_ms(period, t1)
        territory = (t1 - PERIOD_BASE_MS[period]) % int(self.cfg.territory_every_s * 1000) == 0
        for team in (r.home, r.away):
            wc = WindowCalc(self.state, team, period, t0, t1, win)
            wc.min_opp_minutes = self.cfg.pressing_min_opp_minutes
            wc.min_passes = self.cfg.style_min_passes
            calc = wc.compute(territory)
            calc["values"]["formation_out_raw"] = calc["values"]["formation_out"]
            calc["values"]["formation_out"] = self.stable_formation(team,
                                                                    calc["values"]["formation_out"])
            wid = f"w-{team}-{period}-{mmss(t0)}-{mmss(t1)}"
            snap = Snapshot(wid, team, period, play, t1, calc["values"], calc["positions"])
            self.latest[team] = snap
            unusual = self.detector.unusual(snap)
            out.append({"sink": "stats", "kind": "window", "window_id": wid,
                        "match_id": self.match_id, "team_id": team, "period": period,
                        "from_ms": t0, "to_ms": t1, "values": calc["values"],
                        "network": calc["network"], "routes": calc["routes"],
                        "positions": calc["positions"], "unusual": unusual})
            out.append({"sink": "stats", "kind": "series", "match_id": self.match_id,
                        "team_id": team, "period": period, "at_ms": t1, "window_id": wid,
                        "values": {k: calc["values"].get(k) for k in SERIES_KEYS}})
            if "territory" in calc:
                out.append({"sink": "stats", "kind": "territory", "match_id": self.match_id,
                            "team_id": team, "period": period, "at_ms": t1, "window_id": wid,
                            "grid": calc["territory"]})
            for note in self.detector.observe(snap):
                note.update({"sink": "stats", "match_id": self.match_id})
                out.append(note)
                why = self.promoter.promote(note)
                if why and why != "after_crux":
                    out += self.offer(self.shift_trigger(note, why))
        out += self.timed(period, t1)
        return out

    def stable_formation(self, team: str, raw: str | None) -> str | None:
        recent = self.recent_formations.setdefault(team, [])
        recent.append(raw)
        del recent[:-self.cfg.formation_stable_windows]
        if len(recent) == self.cfg.formation_stable_windows and len(set(recent)) == 1:
            self.formation[team] = raw
        return self.formation.get(team)

    def new_trigger(self, type_: str, reason: str, team: str | None, period: int, clock: int,
                    event_ids=None, window_ids=None, before=None, after=None) -> dict:
        tid = f"t-{self.next_trigger:03d}"
        self.next_trigger += 1
        return {"sink": "triggers", "trigger_id": tid, "match_id": self.match_id,
                "type": type_, "reason": reason, "team_id": team,
                "importance": importance(reason, self.minute(period, clock), self.score),
                "at_ms": clock, "period": period, "play_ms": self.play_ms(period, clock),
                "evidence": {"event_ids": list(event_ids or []),
                             "window_ids": list(window_ids or []),
                             "before": before or {}, "after": after or {},
                             "did_it_work": None, "unusual": False},
                "merged_from": [], "summary_of": []}

    def offer(self, trig: dict) -> list[dict]:
        return self.buffer.offer(trig)

    def shift_trigger(self, note: dict, why: str) -> dict:
        team = note["team_id"]
        key = note["change"]
        t = self.new_trigger("shift", "player_change" if key == "player_position" else "shift",
                             team, note["period"], note["at_ms"], window_ids=note["window_ids"],
                             before={key: note["before"]}, after={key: note["after"]})
        t["evidence"]["note_id"] = note["note_id"]
        t["evidence"]["unusual"] = bool(note.get("unusual"))
        t["evidence"]["promoted_because"] = why
        t["evidence"]["since_ms"] = note["since_ms"]
        t["evidence"]["did_it_work"] = self.did_it_work(team, note["since_period"],
                                                        note["since_ms"], note["period"],
                                                        note["at_ms"])
        return t

    def snapshot_values(self, team: str | None) -> dict:
        snap = self.latest.get(team) if team else None
        if not snap:
            return {}
        keys = ("line_height_m", "pressing_per_min", "press_size", "style_dial", "formation_out",
                "control_share", "chaos")
        return {k: snap.values.get(k) for k in keys}

    def on_event(self, ev: CleanEvent) -> list[dict]:
        first = self.state.upsert(ev)
        if not first:
            return []
        out: list[dict] = []
        team = ev.team_id
        reason = None
        if ev.type == "shot" and ev.outcome == "goal" and team:
            self.score[team] = self.score.get(team, 0) + 1
            reason = "goal"
        elif ev.type == "card":
            reason = "red_card" if ev.outcome == "red" else "yellow_card"
        elif ev.type == "sub_on":
            reason = "sub"
        elif ev.type == "conditions" and ev.match_clock_ms > 0:
            reason = "conditions"
        elif ev.type == "stoppage_start" and ev.details:
            self.stoppages[ev.details.get("stoppage_id", "")] = ev.match_clock_ms
        elif ev.type == "stoppage_end" and ev.details:
            began = self.stoppages.pop(ev.details.get("stoppage_id", ""), None)
            if began is not None and ev.match_clock_ms - began >= self.cfg.long_stoppage_s * 1000:
                reason = "stoppage"
        if reason is None:
            return out
        type_ = "external" if reason in ("conditions", "stoppage") else "crux"
        affected = team
        if reason in ("red_card", "yellow_card", "sub") and team:
            affected = team
        elif reason == "goal" and team:
            affected = self.state.roster.other(team)
        snap = self.latest.get(affected) if affected else None
        trig = self.new_trigger(type_, reason, affected, ev.period, ev.match_clock_ms,
                                event_ids=[ev.event_id],
                                window_ids=[snap.window_id] if snap else [],
                                before=self.snapshot_values(affected))
        trig["evidence"]["scorer_team"] = team if reason == "goal" else None
        self.promoter.crux(affected, trig["play_ms"])
        out += self.offer(trig)
        if type_ == "crux" and reason != "yellow_card":
            self.pending_confirm.append({
                "due_play": trig["play_ms"] + int(self.cfg.confirm_due_s * 1000),
                "team": affected, "crux_id": trig["trigger_id"], "event_id": ev.event_id,
                "before": trig["evidence"]["before"],
                "before_window": trig["evidence"]["window_ids"],
                "crux_period": ev.period, "crux_clock": ev.match_clock_ms, "reason": reason})
        return out

    def timed(self, period: int, clock: int) -> list[dict]:
        out: list[dict] = []
        play = self.play_ms(period, clock)
        for minute in self.cfg.check_ins_min:
            if minute in self.check_ins_done:
                continue
            due_period = 1 if minute <= 45 else 2
            if period == due_period and clock >= minute * 60000:
                self.check_ins_done.add(minute)
                r = self.state.roster
                t = self.new_trigger("check_in", "check_in", None, period, clock,
                                     window_ids=[s.window_id for s in self.latest.values()],
                                     after={team: self.snapshot_values(team)
                                            for team in (r.home, r.away)})
                t["evidence"]["previous"] = self.check_in_previous(minute)
                out += self.offer(t)
        if not self.late_done and period == 2 and clock >= self.cfg.late_game_min * 60000:
            self.late_done = True
            out += self.offer(self.new_trigger("external", "late_game", None, period, clock,
                                               after={t: self.snapshot_values(t)
                                                      for t in self.score}))
        for item in list(self.pending_confirm):
            if play >= item["due_play"]:
                self.pending_confirm.remove(item)
                team = item["team"]
                snap = self.latest.get(team)
                t = self.new_trigger("confirm_due", "confirm_due", team, period, clock,
                                     event_ids=[item["event_id"]],
                                     window_ids=item["before_window"] + ([snap.window_id]
                                                                         if snap else []),
                                     before=item["before"], after=self.snapshot_values(team))
                t["evidence"]["crux_trigger_id"] = item["crux_id"]
                t["evidence"]["crux_reason"] = item["reason"]
                t["evidence"]["did_it_work"] = self.did_it_work(
                    team, item["crux_period"], item["crux_clock"], period, clock)
                out += self.offer(t)
        for team, hold in self.buffer.due(play):
            first = hold.items[0]
            s = self.new_trigger("summary", "summary", team, period, clock,
                                 event_ids=sorted({e for t in hold.items
                                                   for e in t["evidence"]["event_ids"]}),
                                 window_ids=first["evidence"]["window_ids"][:1]
                                 + ([self.latest[team].window_id] if team in self.latest else []),
                                 before=first["evidence"]["before"],
                                 after=self.snapshot_values(team))
            s["summary_of"] = [t["trigger_id"] for t in hold.items]
            s["importance"] = max(t["importance"] for t in hold.items)
            out += self.buffer.release(s)
        return out

    def check_in_previous(self, minute: int) -> dict:
        prev = {}
        for team, hist in self.detector.history.items():
            target = self.latest[team].play_ms - 15 * 60000 if team in self.latest else 0
            cands = [s for s in hist if s.play_ms <= target]
            if cands:
                prev[team] = {k: cands[-1].values.get(k) for k in
                              ("line_height_m", "pressing_per_min", "style_dial", "formation_out",
                               "control_share")}
        return prev

    def did_it_work(self, team: str | None, p0: int, c0: int, p1: int, c1: int) -> dict | None:
        if not team:
            return None
        start, now = self.play_ms(p0, c0), self.play_ms(p1, c1)
        span = now - start
        if span <= 60000:
            return None

        def stats(a: int, b: int) -> dict:
            evs = [e for e in self.state.events.values() if e.status == "active"
                   and a <= self.play_ms(e.period, e.match_clock_ms) <= b]
            xg_for = sum(e.provider_xg or 0 for e in evs if e.type == "shot" and e.team_id == team)
            xg_against = sum(e.provider_xg or 0 for e in evs if e.type == "shot"
                             and e.team_id and e.team_id != team)
            onball = [e for e in evs if e.type in ("pass", "take_on", "shot") and e.start]
            mine = [e for e in onball if e.team_id == team]
            r = self.state.roster
            final = [e for e in onball if e.team_id and depth(r, e.team_id, e.start.x) > 70]
            tilt = sum(1 for e in final if e.team_id == team) / len(final) if final else None
            per10 = 600000 / max(b - a, 1)
            return {"xg_for_per10": round(xg_for * per10, 2),
                    "xg_against_per10": round(xg_against * per10, 2),
                    "possession_share": round(len(mine) / len(onball), 2) if onball else None,
                    "field_tilt": round(tilt, 2) if tilt is not None else None}

        return {"before": stats(start - span, start), "after": stats(start, now),
                "span_s": round(span / 1000)}

    def flush(self) -> list[dict]:
        out: list[dict] = []
        for period, clock in self.state.clock_ms.items():
            if clock > 0 and self.next_mark.get(period, 0) <= clock:
                out += self.compute_windows(period, clock)
        return out
