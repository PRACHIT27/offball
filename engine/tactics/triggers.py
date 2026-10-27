from dataclasses import dataclass, field

from engine.tactics.config import TacticsConfig

BASE_IMPORTANCE = {"goal": 1.0, "red_card": 0.9, "shift": 0.6, "conditions": 0.3, "sub": 0.4,
                   "yellow_card": 0.2, "player_change": 0.2, "stoppage": 0.3, "late_game": 0.3,
                   "check_in": 0.5, "confirm_due": 0.6, "summary": 0.6}
BYPASS = {"goal", "red_card"}


def importance(reason: str, minute: float, score: dict) -> float:
    base = BASE_IMPORTANCE.get(reason, 0.4)
    if minute >= 75:
        base += 0.2
    goals = list(score.values()) or [0, 0]
    if len(goals) == 2 and abs(goals[0] - goals[1]) <= 1:
        base += 0.2
    return round(min(base, 1.0), 2)


@dataclass
class TeamHold:
    started: int
    last_added: int
    items: list[dict] = field(default_factory=list)


class TriggerBuffer:
    def __init__(self, cfg: TacticsConfig):
        self.cfg = cfg
        self.sent: dict[str, list[int]] = {}
        self.last_sent: dict[str, int] = {}
        self.holds: dict[str, TeamHold] = {}
        self.counts = {"sent": 0, "held": 0, "summaries": 0}

    def _send(self, trig: dict) -> list[dict]:
        self.counts["sent"] += 1
        team = trig.get("team_id")
        if team and trig["reason"] not in BYPASS and trig["type"] != "check_in":
            self.sent.setdefault(team, []).append(trig["play_ms"])
            self.last_sent[team] = trig["play_ms"]
        return [trig]

    def _hold(self, team: str, trig: dict) -> list[dict]:
        self.counts["held"] += 1
        h = self.holds.get(team)
        if h is None:
            h = self.holds[team] = TeamHold(trig["play_ms"], trig["play_ms"])
        h.items.append(trig)
        h.last_added = trig["play_ms"]
        return []

    def offer(self, trig: dict) -> list[dict]:
        team, now = trig.get("team_id"), trig["play_ms"]
        if trig["reason"] in BYPASS:
            held = self.holds.pop(team, None) if team else None
            if held:
                trig["merged_from"] = [t["trigger_id"] for t in held.items]
                for t in held.items:
                    trig["evidence"]["event_ids"] += [e for e in t["evidence"]["event_ids"]
                                                      if e not in trig["evidence"]["event_ids"]]
            return self._send(trig)
        if trig["type"] == "check_in" or not team:
            return self._send(trig)
        if team in self.holds:
            return self._hold(team, trig)
        recent = [t for t in self.sent.get(team, []) if now - t <= self.cfg.buffer_per_s * 1000]
        self.sent[team] = recent
        last = self.last_sent.get(team)
        if len(recent) >= self.cfg.buffer_max_reviews or (
                last is not None and now - last <= self.cfg.merge_within_s * 1000
                and trig["type"] != "confirm_due"):
            return self._hold(team, trig)
        return self._send(trig)

    def due(self, now: int) -> list[tuple[str, TeamHold]]:
        out = []
        for team, h in list(self.holds.items()):
            if now - h.last_added >= self.cfg.buffer_quiet_s * 1000 or \
                    now - h.started >= self.cfg.buffer_max_hold_s * 1000:
                out.append((team, self.holds.pop(team)))
        return out

    def release(self, summary: dict) -> list[dict]:
        self.counts["summaries"] += 1
        return self._send(summary)
