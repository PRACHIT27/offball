from insights import checker, facts, templates


def _red_card_confirmed(data):
    return facts.build(data.triggers[2], data)  # line 33.8 → 25.9, 3-5-2 → 4-4-1, possession 51 → 58


def _check(text, f, key="analyst.en", tools=None):
    return checker.check({key: text}, f, tools)


def test_template_captions_pass(data):
    for t in data.triggers:
        f = facts.build(t, data)
        r = checker.check(templates.captions(f), f)
        assert r.passed, (t["trigger_id"], r.reasons)


def test_injected_wrong_number_is_caught(data):
    """LLD §14 grounding test."""
    f = _red_card_confirmed(data)
    assert _check("Northgate dropped their line from 33.8 m to 25.9 m.", f).passed
    r = _check("Northgate dropped their line from 33.8 m to 21.9 m.", f)
    assert not r.passed and "21.9" in r.reasons[0]


def test_spanish_caption_with_changed_number_fails(data):
    """LLD §14 back-translation test, caught before back-translation: digits are digits."""
    f = _red_card_confirmed(data)
    assert _check("Northgate retrasa su línea: 33.8 m → 25.9 m.", f, "analyst.es").passed
    assert not _check("Northgate retrasa su línea: 33.8 m → 19.9 m.", f, "analyst.es").passed


def test_rounding_and_differences_are_allowed(data):
    f = _red_card_confirmed(data)
    assert _check("Northgate's line is 8 m deeper: 34 m to 26 m. Possession 58%.", f).passed


def test_number_words_are_checked(data):
    f = _red_card_confirmed(data)
    assert _check("The line dropped from thirty-four to twenty-six metres.", f).passed
    assert not _check("The line dropped by twelve metres.", f).passed
    assert not _check("La línea bajó doce metros.", f, "analyst.es").passed


def test_formations_and_minutes(data):
    f = _red_card_confirmed(data)
    assert _check("Since the red card (70'), Northgate went 3-5-2 to 4-4-1.", f).passed
    r = _check("Northgate now play 5-4-0.", f)
    assert not r.passed and "formation 5-4-0" in r.reasons[0]
    assert not _check("Since the 63rd minute, Northgate went deep.", f).passed


def test_claim_must_match_the_sign(data):
    f = _red_card_confirmed(data)
    r = _check("Northgate push their line higher after the red card.", f)
    assert not r.passed and "went up" in r.reasons[0]
    retracted = facts.build(data.triggers[3], data)  # 33.8 → 34.5: no real change
    assert not _check("Riverside drop deeper since the goal.", retracted).passed


def test_expect_captions_may_predict(data):
    f = facts.build(data.triggers[1], data)
    assert _check("Red card. Expect Northgate to drop deeper.", f, "casual.en").passed


def test_tool_results_ground_numbers(data):
    f = _red_card_confirmed(data)
    tools = [{"tool": "get_pressing", "result": {"pressing_per_min": 6.4}}]
    assert not _check("Northgate press at 6.4 per minute now.", f).passed
    assert _check("Northgate press at 6.4 per minute now.", f, tools=tools).passed


def test_word_limit(data):
    f = _red_card_confirmed(data)
    long = "Northgate dropped deeper " + "and kept going " * 6
    assert not _check(long, f, "casual.en").passed
