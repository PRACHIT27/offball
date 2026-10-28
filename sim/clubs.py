from dataclasses import dataclass, field

import numpy as np

from sim.tactics import TacticProfile

SQUAD = 18
STARTING_SHIRTS = [1, 2, 3, 4, 5, 6, 8, 10, 7, 9, 11]
POSITIONS = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW"]
BENCH_POSITIONS = {12: "ST", 13: "CM", 14: "CB", 15: "RW", 16: "LB", 17: "CM", 18: "GK"}
FIRST = ["Ari", "Bram", "Cato", "Dex", "Eli", "Finn", "Gus", "Hale", "Ivo", "Jory", "Kit", "Lio",
         "Milo", "Nico", "Oren", "Pax", "Quin", "Rafe", "Sol", "Tam", "Ugo", "Vale", "Wren",
         "Yuri", "Zeb", "Ansel", "Bodhi", "Cyrus", "Dario", "Emre"]
LAST = ["Ashby", "Brook", "Calder", "Dunmore", "Ellery", "Fenwick", "Garrow", "Hollis", "Ingram",
        "Jessop", "Kerridge", "Lowther", "Marlow", "Norland", "Oakes", "Pellow", "Quarry",
        "Rowan", "Selby", "Thorne", "Upton", "Varley", "Wexford", "Yardley", "Arkwright",
        "Blythe", "Corwen", "Dacre", "Eskdale", "Farrant"]
SPARE_LAST = ["Alder", "Brackley", "Coniston", "Dalby", "Embleton", "Felling", "Grisedale",
              "Hawes", "Keld", "Langdale", "Mardale", "Nenthead", "Ormside", "Patterdale",
              "Ravenglass", "Sedbergh", "Thirlby", "Wasdale", "Yarrow", "Allendale", "Bewley",
              "Cawood", "Dentdale", "Eamont", "Fellside", "Glaisdale", "Hartside", "Kirkby",
              "Lorton", "Mosedale"]
ABILITY_PROFILES = {
    "GK": {"goalkeeping": 80, "passing": 55, "pace": 50, "tackling": 30, "dribbling": 30},
    "CB": {"tackling": 76, "passing": 62, "pace": 66, "dribbling": 50, "finishing": 35},
    "RB": {"tackling": 68, "passing": 66, "pace": 78, "dribbling": 62, "finishing": 42},
    "LB": {"tackling": 68, "passing": 66, "pace": 78, "dribbling": 62, "finishing": 42},
    "DM": {"tackling": 72, "passing": 74, "pace": 66, "dribbling": 60, "finishing": 48},
    "CM": {"tackling": 62, "passing": 76, "pace": 70, "dribbling": 68, "finishing": 58},
    "RW": {"tackling": 40, "passing": 70, "pace": 86, "dribbling": 80, "finishing": 70},
    "LW": {"tackling": 40, "passing": 70, "pace": 86, "dribbling": 80, "finishing": 70},
    "ST": {"tackling": 38, "passing": 64, "pace": 80, "dribbling": 74, "finishing": 80},
}


@dataclass
class Manager:
    manager_id: str
    name: str
    identity: TacticProfile
    preferred_formations: list[str]
    reaction_style: dict
    risk_appetite: float


@dataclass
class Club:
    club_id: str
    name: str
    traditional_style: str
    manager: Manager
    seed: int
    players: list[dict] = field(default_factory=list)


def _player(club_id: str, number: int, rng: np.random.Generator) -> dict:
    position = POSITIONS[STARTING_SHIRTS.index(number)] if number in STARTING_SHIRTS \
        else BENCH_POSITIONS[number]
    base = ABILITY_PROFILES[position]
    abilities = {k: int(np.clip(v + rng.normal(0, 6), 25, 96)) for k, v in base.items()}
    for key in ("acceleration", "vision", "positioning", "stamina", "discipline"):
        abilities[key] = int(np.clip(rng.normal(68, 9), 35, 95))
    abilities.setdefault("goalkeeping", 20)
    abilities.setdefault("finishing", 40)
    goals = int(rng.integers(0, 60 if position in ("ST", "RW", "LW") else 15))
    apps = int(rng.integers(20, 240))
    near = []
    if goals % 50 == 49 or goals in (24, 99):
        near.append(f"1 away from {goals + 1} goals")
    if apps % 50 == 49:
        near.append(f"1 away from {apps + 1} appearances")
    return {
        "player_id": f"{club_id}-{number:02d}",
        "number": number,
        "name": f"{FIRST[rng.integers(len(FIRST))]} {LAST[rng.integers(len(LAST))]}",
        "position": position,
        "starting": number in STARTING_SHIRTS,
        "abilities": abilities,
        "career": {"appearances": apps, "goals": goals,
                   "assists": int(rng.integers(0, 40)), "milestones_near": near},
    }


def _club(club_id, name, style, seed, manager: Manager) -> Club:
    rng = np.random.default_rng(seed)
    club = Club(club_id, name, style, manager, seed)
    club.players = [_player(club_id, n, rng) for n in range(1, SQUAD + 1)]
    return club


CLUBS: dict[str, Club] = {
    "RIV": _club("RIV", "Riverside Athletic", "Patient possession side for a decade", 701, Manager(
        "MGR-RIV", "Elena Marsh",
        TacticProfile("4-3-3", 42, 12, 3, 34, 52, 0.25, 1.0, True),
        ["4-3-3", "3-5-2"],
        {"on_red_card": {"line_height_m": -10, "pressers": -2, "delay_s": 30},
         "on_lead_late": {"from_minute": 60, "line_height_m": -6, "tempo_s": 0.4,
                          "delay_s": 300},
         "on_trailing_late": {"from_minute": 70, "line_height_m": 4, "pressers": 1,
                              "delay_s": 60}},
        0.6)),
    "NGU": _club("NGU", "Northgate United", "Direct, hard-running counter-attacking side", 702,
                 Manager(
        "MGR-NGU", "Callum Hartwell",
        TacticProfile("4-4-2", 37, 9, 2, 38, 50, 0.6, 1.5, False),
        ["4-4-2", "3-5-2"],
        {"on_red_card": {"line_height_m": -12, "pressers": -1, "delay_s": 30},
         "on_lead_late": {"from_minute": 60, "line_height_m": -7, "delay_s": 300},
         "on_trailing_late": {"from_minute": 70, "line_height_m": 5, "pressers": 1,
                              "delay_s": 60}},
        0.8)),
    "KVA": _club("KVA", "Kestrel Vale", "Energetic high-pressing side", 703, Manager(
        "MGR-KVA", "Ines Varga",
        TacticProfile("3-5-2", 40, 13, 3, 33, 54, 0.4, 1.2, True),
        ["3-5-2", "4-3-3"],
        {"on_red_card": {"line_height_m": -8, "pressers": -1, "delay_s": 30},
         "on_lead_late": {"from_minute": 65, "line_height_m": -5, "delay_s": 240},
         "on_trailing_late": {"from_minute": 65, "line_height_m": 4, "pressers": 1,
                              "delay_s": 60}},
        0.7)),
}


def _unique_surnames(clubs: dict[str, Club]) -> None:
    used: set[str] = set()
    spare = iter(SPARE_LAST)
    for club in clubs.values():
        for p in club.players:
            first, last = p["name"].split(" ", 1)
            if last in used:
                last = next(s for s in spare if s not in used)
                p["name"] = f"{first} {last}"
            used.add(last)


_unique_surnames(CLUBS)


def history(club: Club, rng: np.random.Generator) -> dict:
    ident = club.manager.identity
    last_10 = []
    for _ in range(10):
        last_10.append({
            "result": str(rng.choice(["W", "D", "L"], p=[0.45, 0.27, 0.28])),
            "line_height_m": round(float(ident.line_height_m + rng.normal(0, 2)), 1),
            "pressing_per_min": round(float(1.2 + 0.5 * ident.pressers + rng.normal(0, 0.3)), 2),
            "avg_pass_length_m": round(float(14 + 14 * ident.pass_length_pref
                                             + rng.normal(0, 1.5)), 1),
            "possession_pct": round(float(60 - 20 * ident.pass_length_pref
                                          + rng.normal(0, 4)), 1),
            "formation": ident.formation,
        })
    keys = ["line_height_m", "pressing_per_min", "avg_pass_length_m", "possession_pct"]
    season = {k: round(float(np.mean([m[k] for m in last_10])), 2) for k in keys}
    spread = {k: round(float(np.std([m[k] for m in last_10])), 2) for k in keys}
    return {"season_averages": season, "season_spread": spread, "last_10": last_10}


def prematch(match_id: str, home: Club, away: Club, conditions: dict) -> dict:
    def side(club: Club) -> dict:
        rng = np.random.default_rng(club.seed + 1)
        m = club.manager
        return {
            "club_id": club.club_id,
            "name": club.name,
            "traditional_style": club.traditional_style,
            "manager": {"manager_id": m.manager_id, "name": m.name,
                        "identity": m.identity.to_dict(),
                        "preferred_formations": m.preferred_formations},
            "history": history(club, rng),
            "players": [{k: p[k] for k in ("player_id", "number", "name", "position", "starting",
                                           "career")} for p in club.players],
        }

    return {"match_id": match_id, "home": side(home), "away": side(away),
            "conditions": conditions}
