"""The code half of the checker (LLD §8): every number in a caption must come from the trigger's
facts or a tool result from the same run, and claims of change must agree with the sign of the
difference. Content Safety and the Translator back-check plug in on top (insights/safety.py).
"""

import re
from dataclasses import dataclass, field

WORD_LIMIT = {"analyst": 30, "casual": 18, "supporter_home": 22, "supporter_away": 22}

# Number words a model may write instead of digits ("thirty-four"). "one"/"uno"/"una"/"एक" are
# left out: they are mostly articles ("one change", "una línea").
_EN = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
       "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
       "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
       "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
       "ninety": 90, "hundred": 100}
_ES = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
       "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
       "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
       "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100}
_HI = {"दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "सात": 7, "आठ": 8, "नौ": 9,
       "दस": 10, "बीस": 20, "तीस": 30, "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70,
       "अस्सी": 80, "नब्बे": 90, "सौ": 100}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

FORMATION = re.compile(r"\b\d(?:-\d){2,3}\b")
STOPPAGE_MINUTE = re.compile(r"\b(\d{2,3})\+(\d{1,2})'")
NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)(\s*(?:m\b|%|/min|°))?")

# Claims of change, per measure and direction (rule 4)
CLAIMS = {
    ("line_height_m", "down"): r"drop(?:s|ped|ping)? (?:back|deeper)|deeper|sit(?:s|ting)? deeper|retreat|lower(?:ed)? (?:their |the )?line|retrasa|repliega|पीछे",
    ("line_height_m", "up"): r"push(?:es|ed|ing)? (?:their |the )?line (?:up|higher)|higher line|line higher|adelanta|आगे",
    ("pressing_per_min", "up"): r"press(?:es|ing)? (?:more|harder)|more pressing|step(?:s|ped)? up the press|presiona más|más presión|ज़्यादा प्रेस",
    ("pressing_per_min", "down"): r"press(?:es|ing)? less|less pressing|stop(?:s|ped)? pressing|eas(?:e|es|ed) off|presiona menos|menos presión|कम प्रेस",
}


@dataclass
class CheckResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _numbers_in(obj, out: set[float], formations: set[str], minutes: set[str]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        formations.update(FORMATION.findall(obj))
        minutes.update(f"{a}+{b}" for a, b in STOPPAGE_MINUTE.findall(obj))
        for n in re.findall(r"\d+(?:\.\d+)?", FORMATION.sub(" ", obj)):
            out.add(float(n))
    elif isinstance(obj, dict):
        b, a = obj.get("before"), obj.get("after")
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) and \
                not isinstance(b, bool) and not isinstance(a, bool):
            out.add(round(abs(a - b), 2))  # "dropped 8 m" is a difference of two facts
        for v in obj.values():
            _numbers_in(v, out, formations, minutes)
    elif isinstance(obj, (list, tuple)):
        if len(obj) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                 for v in obj):
            out.add(round(abs(obj[1] - obj[0]), 2))
        for v in obj:
            _numbers_in(v, out, formations, minutes)


class Grounding:
    """The numbers a caption may use: the facts plus this run's tool results."""

    def __init__(self, facts: dict, tool_results: list | None = None):
        self.numbers: set[float] = set()
        self.formations: set[str] = set()
        self.minutes: set[str] = set()
        _numbers_in(facts, self.numbers, self.formations, self.minutes)
        _numbers_in(tool_results or [], self.numbers, self.formations, self.minutes)
        # Percent shares stored as 0.58 may be written as 58%
        self.numbers |= {round(v * 100, 1) for v in self.numbers if 0 < v < 1}
        self.facts = facts

    def has(self, n: float, unit: str) -> bool:
        tol = 0.5 if unit == "m" else 1.0 if unit == "%" else 0.05
        return any(abs(n - v) <= tol or (n == int(n) and round(v) == n) for v in self.numbers)


def _word_numbers(text: str, lang: str) -> list[float]:
    words = {"en": _EN, "es": _ES, "hi": _HI}.get(lang, _EN)
    found = []
    for token in re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)?", text.lower()):
        parts = token.split("-")
        if all(p in words for p in parts):
            found.append(float(sum(words[p] for p in parts)))
    return found


def check_numbers(text: str, lang: str, g: Grounding) -> list[str]:
    reasons = []
    text = text.translate(_DEVANAGARI_DIGITS)
    for f in FORMATION.findall(text):
        if f not in g.formations:
            reasons.append(f"formation {f} is not in the evidence")
    text = FORMATION.sub(" ", text)
    for a, b in STOPPAGE_MINUTE.findall(text):
        if f"{a}+{b}" not in g.minutes:
            reasons.append(f"minute {a}+{b}' is not in the evidence")
    text = STOPPAGE_MINUTE.sub(" ", text)
    for raw, unit in NUMBER.findall(text):
        n = float(raw.replace(",", "."))
        u = (unit or "").strip()
        if not g.has(n, "m" if u == "m" else "%" if u == "%" else ""):
            reasons.append(f"number {raw}{u} is not in the evidence")
    for n in _word_numbers(text, lang):
        if not g.has(n, ""):
            reasons.append(f"number word for {n:g} is not in the evidence")
    return reasons


def _directions(facts: dict) -> set[tuple[str, str]]:
    changes = list(facts.get("changes") or [])
    if facts.get("change"):
        changes.append(facts["change"])
    return {(c["measure"], c.get("direction")) for c in changes if c.get("direction")}


def check_claims(text: str, facts: dict) -> list[str]:
    # An expect caption predicts; the claim is checked later at confirm-due time
    if facts.get("kind") in ("expect",):
        return []
    have = _directions(facts)
    reasons = []
    for (measure, direction), pattern in CLAIMS.items():
        if re.search(pattern, text, re.IGNORECASE) and (measure, direction) not in have:
            reasons.append(f"claims {measure.replace('_', ' ')} went {direction}, "
                           f"the evidence doesn't show that")
    return reasons


def check_caption(key: str, text: str, g: Grounding) -> list[str]:
    viewer, lang = key.rsplit(".", 1)
    reasons = check_numbers(text, lang, g) + check_claims(text, g.facts)
    limit = WORD_LIMIT.get(viewer)
    if limit and lang != "hi" and len(text.split()) > limit:
        reasons.append(f"{len(text.split())} words, the limit for {viewer} is {limit}")
    return reasons


def check(captions: dict[str, str], facts: dict, tool_results: list | None = None) -> CheckResult:
    g = Grounding(facts, tool_results)
    reasons = [f"{key}: {r}" for key, text in captions.items() for r in check_caption(key, text, g)]
    return CheckResult(not reasons, reasons)
