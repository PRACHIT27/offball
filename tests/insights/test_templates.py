import re

from insights import facts, templates
from insights.local import template_insight


def test_twelve_captions_for_every_trigger(data):
    for t in data.triggers:
        caps = template_insight(t, data).captions
        assert len(caps) == 15, t["trigger_id"]
        assert all(caps.values()), t["trigger_id"]


def test_kinds(data):
    kinds = {t["trigger_id"]: facts.build(t, data)["kind"] for t in data.triggers}
    assert kinds["t-001"] == "expect"
    assert kinds["t-003"] == "confirmed"  # line 33.8 → 25.9 is past the 6 m threshold
    assert kinds["t-004"] == "retracted"  # 33.8 → 34.5 is not


def test_red_card_story(data):
    expect = template_insight(data.triggers[1], data).captions
    confirmed = template_insight(data.triggers[2], data).captions
    assert "Expect Northgate United to drop deeper" in expect["casual.en"]
    assert "33.8 m → 25.9 m" in confirmed["analyst.en"]
    assert "34 m → 26 m" in confirmed["casual.en"]
    assert "Possession 51% → 58%" in confirmed["analyst.en"]


def test_score_counts_goals_up_to_the_trigger(data):
    f = facts.build(data.triggers[6], data)  # 30' check-in, after the 23' goal
    assert f["score"] == {"home": 1, "away": 0}
    assert "Riverside Athletic 1–0 Northgate United" in templates.captions(f)["casual.en"]


def test_supporters_see_the_other_club_framed_as_opponents(data):
    goal = template_insight(data.triggers[0], data).captions  # Riverside score
    assert not goal["supporter_home.en"].startswith("Opponents")
    assert goal["supporter_away.en"].startswith("Opponents: ")
    assert goal["supporter_away.es"].startswith("Rivales: ")


def test_hindi_uses_danda_but_keeps_decimals(data):
    hi = template_insight(data.triggers[2], data).captions["analyst.hi"]
    assert hi.endswith("।")
    assert "33.8 m" in hi


def test_every_caption_number_comes_from_the_trigger(data):
    """Templates only use evidence numbers, the score and minutes (IG-22)."""
    for t in data.triggers:
        f = facts.build(t, data)
        allowed = set(re.findall(r"\d+(?:\.\d+)?", str(f)))
        allowed |= {str(round(float(n))) for n in list(allowed)}
        for text in templates.captions(f).values():
            for n in re.findall(r"\d+(?:\.\d+)?", text):
                assert n in allowed, (t["trigger_id"], n, text)
