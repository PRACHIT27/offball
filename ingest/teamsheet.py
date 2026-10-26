"""Team sheet: maps provider IDs and shirt numbers to our player IDs (FR-7, LLD §13.3)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr

from ingest.raw import FeedALineup, Prematch

Side = Literal["home", "away"]


class UnknownId(LookupError):
    """A provider ID or shirt number that is not on the team sheet (dead-lettered, FR-10)."""


class TeamSheetPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_id: str
    number: int
    provider_player_id: int | None = None


class TeamSheetSide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    club_id: str
    provider_team_id: int | None = None
    players: list[TeamSheetPlayer]


class TeamSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_id: str
    home: TeamSheetSide
    away: TeamSheetSide

    _by_provider_player: dict[int, tuple[str, str]] = PrivateAttr(default_factory=dict)
    _by_provider_team: dict[int, str] = PrivateAttr(default_factory=dict)
    _by_shirt: dict[tuple[Side, int], str] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context) -> None:
        for side_name, side in (("home", self.home), ("away", self.away)):
            if side.provider_team_id is not None:
                self._by_provider_team[side.provider_team_id] = side.club_id
            for p in side.players:
                self._by_shirt[(side_name, p.number)] = p.player_id
                if p.provider_player_id is not None:
                    self._by_provider_player[p.provider_player_id] = (side.club_id, p.player_id)

    @property
    def has_lineup(self) -> bool:
        return bool(self._by_provider_player)

    def side_of(self, club_id: str) -> Side:
        return "home" if club_id == self.home.club_id else "away"

    def player_from_feed_a(self, provider_player_id: int) -> tuple[str, str]:
        """Feed A player ID → (club_id, player_id)."""
        try:
            return self._by_provider_player[provider_player_id]
        except KeyError:
            raise UnknownId(f"feed A playerId {provider_player_id} not in lineup") from None

    def team_from_feed_a(self, provider_team_id: int) -> str:
        try:
            return self._by_provider_team[provider_team_id]
        except KeyError:
            raise UnknownId(f"feed A teamId {provider_team_id} not in lineup") from None

    def feed_b_shirts(self) -> dict[tuple[Side, int], str]:
        """Plain dict for hot loops: (side, shirt) → player_id."""
        return self._by_shirt

    def player_from_feed_b(self, side: Side, shirt: int) -> str:
        try:
            return self._by_shirt[(side, shirt)]
        except KeyError:
            raise UnknownId(f"feed B {side} shirt {shirt} not on team sheet") from None


def from_prematch(prematch: Prematch) -> TeamSheet:
    def side(s) -> TeamSheetSide:
        return TeamSheetSide(
            club_id=s.club_id,
            players=[TeamSheetPlayer(player_id=p.player_id, number=p.number) for p in s.players],
        )

    return TeamSheet(match_id=prematch.match_id, home=side(prematch.home), away=side(prematch.away))


def with_lineup(sheet: TeamSheet, lineup: FeedALineup) -> TeamSheet:
    """Attach feed A's numeric team and player IDs, matched by side and shirt number."""
    sides = {}
    for team in lineup.teams:
        current = sheet.home if team.side == "home" else sheet.away
        by_number = {p.number: p for p in current.players}
        players = []
        for lp in team.players:
            if lp.shirt not in by_number:
                raise UnknownId(f"lineup {team.side} shirt {lp.shirt} not on team sheet")
            players.append(by_number.pop(lp.shirt).model_copy(
                update={"provider_player_id": lp.playerId}))
        players.extend(by_number.values())
        sides[team.side] = current.model_copy(
            update={"provider_team_id": team.teamId, "players": players})
    if set(sides) != {"home", "away"}:
        raise UnknownId("lineup must list one home and one away team")
    return TeamSheet(match_id=sheet.match_id, home=sides["home"], away=sides["away"])
