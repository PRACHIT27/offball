import asyncio

from insights import checker, facts
from insights.safety import Safety


class FakeSafety(Safety):
    """Translator and Content Safety stubbed: back-translations and flags are given."""

    def __init__(self, english: dict, flagged: set):
        self.english, self.flagged = english, flagged

    async def back_translate(self, captions):
        return {k: self.english[k] for k in captions if not k.endswith(".en")}

    async def harmful(self, text):
        return ["content safety: Hate severity 4"] if text in self.flagged else []


def test_back_translation_catches_a_wrong_claim(data):
    """LLD §14 back-translation test: the Spanish caption claims the opposite direction."""
    f = facts.build(data.triggers[2], data)  # line 33.8 → 25.9
    g = checker.Grounding(f)
    caps = {"analyst.en": "Northgate dropped deeper: 33.8 m → 25.9 m.",
            "analyst.es": "Northgate adelanta su línea: 33.8 m → 25.9 m."}
    s = FakeSafety({"analyst.es": "Northgate raises its line: 33.8 m → 25.9 m."}, set())
    reasons = asyncio.run(s.review(caps, g))
    assert reasons["analyst.en"] == []
    assert any("back-translation" in r for r in reasons["analyst.es"])


def test_content_safety_flags_reach_the_checker(data):
    f = facts.build(data.triggers[2], data)
    caps = {"casual.en": "a harmful caption"}
    reasons = asyncio.run(FakeSafety({}, {"a harmful caption"}).review(caps, checker.Grounding(f)))
    assert reasons["casual.en"] == ["content safety: Hate severity 4"]
