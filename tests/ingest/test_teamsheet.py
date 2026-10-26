import pytest

from ingest.raw import FeedALineup, Prematch
from ingest.teamsheet import UnknownId, from_prematch, with_lineup
from tests import factories


@pytest.fixture
def sheet():
    base = from_prematch(Prematch.model_validate(factories.prematch()))
    return with_lineup(base, FeedALineup.model_validate(factories.lineup()))


def test_feed_a_ids_map_to_our_ids(sheet):
    assert sheet.player_from_feed_a(50107) == ("RIV", "RIV-07")
    assert sheet.team_from_feed_a(202) == "NGU"


def test_feed_b_shirts_map_to_our_ids(sheet):
    assert sheet.player_from_feed_b("away", 4) == "NGU-04"


@pytest.mark.parametrize("lookup", [
    lambda s: s.player_from_feed_a(99999),
    lambda s: s.team_from_feed_a(303),
    lambda s: s.player_from_feed_b("home", 77),
])
def test_unknown_ids_raise(sheet, lookup):
    with pytest.raises(UnknownId):
        lookup(sheet)


def test_lineup_with_unknown_shirt_is_rejected():
    base = from_prematch(Prematch.model_validate(factories.prematch()))
    bad = factories.lineup()
    bad["teams"][0]["players"][0]["shirt"] = 88
    with pytest.raises(UnknownId):
        with_lineup(base, FeedALineup.model_validate(bad))


def test_team_sheet_round_trips_through_json(sheet):
    again = type(sheet).model_validate_json(sheet.model_dump_json())
    assert again.player_from_feed_a(50107) == ("RIV", "RIV-07")
