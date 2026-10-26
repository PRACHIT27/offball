"""Small hand-built inputs for unit tests. Fictional clubs only."""


def prematch(match_id="m001", squad=14):
    def side(club, name):
        return {
            "club_id": club, "name": name,
            "players": [
                {"player_id": f"{club}-{n:02d}", "number": n, "name": f"{club} Player {n}",
                 "position": "GK" if n == 1 else "MF", "starting": n <= 11}
                for n in range(1, squad + 1)
            ],
        }
    return {"match_id": match_id, "home": side("RIV", "Riverside Athletic"),
            "away": side("NGU", "Northgate United")}


def lineup(match_id="m001", squad=14):
    return {
        "msgType": "lineup", "matchId": match_id,
        "teams": [
            {"teamId": 101, "side": "home",
             "players": [{"playerId": 50100 + n, "shirt": n} for n in range(1, squad + 1)]},
            {"teamId": 202, "side": "away",
             "players": [{"playerId": 50200 + n, "shirt": n} for n in range(1, squad + 1)]},
        ],
    }
