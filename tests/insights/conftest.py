import pytest

from insights.data import MatchData


def _side(club, name, first):
    return {"club_id": club, "name": name, "players": [
        {"player_id": f"{club}-{n:02d}", "number": n, "name": f"{first} {club.title()}{n}",
         "position": "CM", "starting": n <= 11} for n in range(1, 15)]}


def _event(eid, typ, team, player, period, clock, outcome=None, details=None):
    return {"event_id": eid, "version": 1, "status": "active", "match_id": "m1",
            "match_clock_ms": clock, "period": period, "type": typ, "team_id": team,
            "player_id": player, "target_player_id": None, "start": None, "end": None,
            "outcome": outcome, "qualifiers": [], "provider_xg": None, "details": details}


def trig(tid, typ, reason, team, period, clock, **ev):
    evidence = {"event_ids": [], "window_ids": ["w-1"], "before": {}, "after": {},
                "did_it_work": None, "unusual": False, **ev}
    return {"sink": "triggers", "trigger_id": tid, "match_id": "m1", "type": typ,
            "reason": reason, "team_id": team, "importance": 0.8, "at_ms": clock,
            "period": period, "play_ms": clock, "evidence": evidence, "merged_from": [],
            "summary_of": []}


STATE = {"line_height_m": 33.8, "pressing_per_min": 3.2, "press_size": 1.1, "style_dial": 50.0,
         "formation_out": "3-5-2", "control_share": 0.5, "chaos": 60.0}


@pytest.fixture
def data() -> MatchData:
    d = MatchData("m1", {"match_id": "m1", "home": _side("RIV", "Riverside Athletic", "Ana"),
                         "away": _side("NGU", "Northgate United", "Bo")})
    for e in (_event("e-000001", "shot", "RIV", "RIV-09", 1, 1_400_000, "goal"),
              _event("e-000002", "card", "NGU", "NGU-04", 2, 4_200_000, "red"),
              _event("e-000003", "conditions", None, None, 2, 3_300_000,
                     details={"weather": "heavy_rain", "temperature_c": 13, "pitch": "wet"}),
              _event("e-000004", "sub_on", "RIV", "RIV-12", 2, 3_630_000),
              _event("e-000005", "sub_off", "RIV", "RIV-07", 2, 3_630_000)):
        d.events[e["event_id"]] = e
    dw = {"before": {"xg_for_per10": 0.1, "possession_share": 0.51},
          "after": {"xg_for_per10": 0.0, "possession_share": 0.58}, "span_s": 300}
    d.triggers = [
        trig("t-001", "crux", "goal", "NGU", 1, 1_401_000, event_ids=["e-000001"],
             before=STATE, scorer_team="RIV"),
        trig("t-002", "crux", "red_card", "NGU", 2, 4_201_000, event_ids=["e-000002"],
             before=STATE),
        trig("t-003", "confirm_due", "confirm_due", "NGU", 2, 4_441_000,
             event_ids=["e-000002"], before=STATE,
             after={**STATE, "line_height_m": 25.9, "formation_out": "4-4-1"},
             did_it_work=dw, crux_reason="red_card", crux_trigger_id="t-002"),
        trig("t-004", "confirm_due", "confirm_due", "RIV", 2, 4_500_000, before=STATE,
             after={**STATE, "line_height_m": 34.5}, crux_reason="goal",
             crux_trigger_id="t-001"),
        trig("t-005", "shift", "shift", "RIV", 1, 610_000, before={"line_height_m": 28.7},
             after={"line_height_m": 35.0}, since_ms=310_000, unusual=True),
        trig("t-006", "shift", "shift", "NGU", 2, 3_100_000, before={"formation_out": "4-4-2"},
             after={"formation_out": "3-5-2"}, since_ms=2_820_000),
        trig("t-007", "check_in", "check_in", None, 1, 1_800_000,
             after={"RIV": STATE, "NGU": {**STATE, "line_height_m": 30.0}}),
        trig("t-008", "external", "conditions", None, 2, 3_300_000, event_ids=["e-000003"]),
        trig("t-009", "summary", "summary", "RIV", 1, 750_000, after=STATE),
        trig("t-010", "crux", "sub", "RIV", 2, 3_631_000, event_ids=["e-000004"], before=STATE),
        trig("t-011", "external", "late_game", None, 2, 5_100_000,
             after={"RIV": STATE, "NGU": STATE}),
    ]
    return d
