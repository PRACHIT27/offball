"""Template captions: written from the facts alone, so every number is grounded by construction.
The fallback when agents time out or the checker rejects twice (IG-25), and local mode without
Foundry (IG-31). Twelve captions per insight: 4 viewer types × en, es, hi (LLD §7).
"""

import re

VIEWER_TYPES = ("analyst", "casual", "supporter_home", "supporter_away")
LANGUAGES = ("en", "es", "hi")

LABEL = {
    "en": {"line_height_m": "defensive line", "pressing_per_min": "pressing",
           "formation_out": "shape", "style_dial": "style dial"},
    "es": {"line_height_m": "línea defensiva", "pressing_per_min": "presión",
           "formation_out": "dibujo", "style_dial": "estilo"},
    "hi": {"line_height_m": "डिफेंसिव लाइन", "pressing_per_min": "प्रेसिंग",
           "formation_out": "फ़ॉर्मेशन", "style_dial": "खेल-शैली"},
}
OPPONENTS = {"en": "Opponents", "es": "Rivales", "hi": "विरोधी टीम"}
CRUX_NAME = {
    "en": {"goal": "goal", "red_card": "red card", "yellow_card": "yellow card", "sub": "substitution"},
    "es": {"goal": "gol", "red_card": "roja", "yellow_card": "amarilla", "sub": "cambio"},
    "hi": {"goal": "गोल", "red_card": "रेड कार्ड", "yellow_card": "येलो कार्ड", "sub": "सब्स्टीट्यूशन"},
}
WEATHER = {
    "en": {"clear": "clear skies", "heavy_rain": "heavy rain", "rain": "rain", "wind": "strong wind",
           "snow": "snow"},
    "es": {"clear": "cielo despejado", "heavy_rain": "lluvia intensa", "rain": "lluvia",
           "wind": "viento fuerte", "snow": "nieve"},
    "hi": {"clear": "साफ़ मौसम", "heavy_rain": "तेज़ बारिश", "rain": "बारिश", "wind": "तेज़ हवा",
           "snow": "बर्फ़"},
}


def _num(v, precise: bool) -> str:
    if isinstance(v, str):
        return v
    return f"{v:.1f}" if precise else f"{v:.0f}"


def value(key: str, v, lang: str, precise: bool) -> str:
    if key == "line_height_m":
        return f"{_num(v, precise)} m"
    if key == "pressing_per_min":
        return f"{v:.1f}/min"
    return _num(v, precise)


def surname(name: str | None) -> str:
    return (name or "").split(" ")[-1]


def score_line(f: dict) -> str:
    return f"{f['home_name']} {f['score']['home']}–{f['score']['away']} {f['away_name']}"


# ---------- per kind: returns {lang: {"analyst": str, "casual": str}} ----------


def _change_text(c: dict, team: str, lang: str, precise: bool) -> str:
    key, b, a = c["measure"], c["before"], c["after"]
    lab = LABEL[lang].get(key, key)
    arrow = f"{value(key, b, lang, precise)} → {value(key, a, lang, precise)}"
    up = c.get("direction") == "up"
    if key == "line_height_m":
        return {"en": f"{team} {'push their line up' if up else 'drop deeper'}: {lab} {arrow}",
                "es": f"{team} {'adelanta' if up else 'retrasa'} su {lab}: {arrow}",
                "hi": f"{team} ने {lab} {'आगे' if up else 'पीछे'} की: {arrow}"}[lang]
    if key == "pressing_per_min":
        return {"en": f"{team} {'press more' if up else 'press less'}: {arrow}",
                "es": f"{team} {'presiona más' if up else 'presiona menos'}: {arrow}",
                "hi": f"{team} अब {'ज़्यादा' if up else 'कम'} प्रेस कर रही है: {arrow}"}[lang]
    if key == "formation_out":
        return {"en": f"{team} switch shape: {b} → {a}",
                "es": f"{team} cambia de dibujo: {b} → {a}",
                "hi": f"{team} ने फ़ॉर्मेशन बदला: {b} → {a}"}[lang]
    return {"en": f"{team} change their {lab}: {arrow}",
            "es": f"{team} cambia su {lab}: {arrow}",
            "hi": f"{team} ने {lab} बदली: {arrow}"}[lang]


def _state_text(state: dict, lang: str, precise: bool) -> str:
    parts = [f"{LABEL[lang][k]} {value(k, v, lang, precise)}" for k, v in state.items()
             if k in ("line_height_m", "pressing_per_min", "formation_out")]
    return ", ".join(parts)


def _expect(f: dict) -> dict:
    e, team = f.get("event") or {}, f.get("team_name") or ""
    reason, minute = f["reason"], f["minute"]
    out = {}
    for lang in LANGUAGES:
        line = f.get("state", {}).get("line_height_m")
        watch = {"en": f"Watch how {team} respond", "es": f"Atentos a la respuesta de {team}",
                 "hi": f"देखिए {team} कैसे जवाब देती है"}[lang]
        if reason == "goal":
            head = {"en": f"Goal for {e.get('team_name')}! {surname(e.get('player'))} scores ({minute})",
                    "es": f"¡Gol de {e.get('team_name')}! Marca {surname(e.get('player'))} ({minute})",
                    "hi": f"{e.get('team_name')} का गोल! {surname(e.get('player'))} ने किया ({minute})"}[lang]
            casual = f"{head}. {watch}."
        elif reason == "red_card":
            head = {"en": f"Red card for {surname(e.get('player'))} ({team}, {minute})",
                    "es": f"Roja para {surname(e.get('player'))} ({team}, {minute})",
                    "hi": f"{surname(e.get('player'))} को रेड कार्ड ({team}, {minute})"}[lang]
            watch = {"en": f"Expect {team} to drop deeper", "es": f"{team} debería replegarse",
                     "hi": f"{team} अब पीछे हटकर खेल सकती है"}[lang]
            casual = f"{head}. {watch}."
        elif reason == "sub":
            on, off = surname(e.get("player_on")), surname(e.get("player_off"))
            head = {"en": f"{team} change: {on} on for {off}" if off else f"{team} bring on {on}",
                    "es": f"Cambio en {team}: entra {on} por {off}" if off else f"Entra {on} en {team}",
                    "hi": f"{team} में बदलाव: {off} की जगह {on}" if off else f"{team} में {on} आए"}[lang]
            casual = f"{head}."
        else:
            head = {"en": f"Yellow card for {surname(e.get('player'))} ({team}, {minute})",
                    "es": f"Amarilla para {surname(e.get('player'))} ({team}, {minute})",
                    "hi": f"{surname(e.get('player'))} को येलो कार्ड ({team}, {minute})"}[lang]
            casual = f"{head}."
        analyst = casual
        if line is not None and reason in ("goal", "red_card", "sub"):
            now = {"en": f"{LABEL[lang]['line_height_m'].capitalize()} now {value('line_height_m', line, lang, True)}",
                   "es": f"{LABEL[lang]['line_height_m'].capitalize()} ahora en {value('line_height_m', line, lang, True)}",
                   "hi": f"अभी {LABEL[lang]['line_height_m']} {value('line_height_m', line, lang, True)} पर"}[lang]
            analyst = f"{casual} {now} ({team})."
        out[lang] = {"analyst": analyst, "casual": casual}
    return out


def _confirmed(f: dict) -> dict:
    team, out = f["team_name"], {}
    crux = f.get("crux_reason") or ""
    for lang in LANGUAGES:
        cname = CRUX_NAME[lang].get(crux, crux)
        since = {"en": f"Since the {cname} ({f.get('crux_minute', '')})",
                 "es": f"Desde la {cname} ({f.get('crux_minute', '')})" if crux in ("red_card", "yellow_card")
                 else f"Desde el {cname} ({f.get('crux_minute', '')})",
                 "hi": f"{cname} ({f.get('crux_minute', '')}) के बाद से"}[lang]
        if f["kind"] == "confirmed":
            first = f["changes"][0]
            casual = f"{since}: {_change_text(first, team, lang, False)}."
            analyst = f"{since}: " + "; ".join(_change_text(c, team, lang, True)
                                               for c in f["changes"][:2]) + "."
        else:
            same = {"en": f"{team} haven't changed much", "es": f"{team} apenas ha cambiado",
                    "hi": f"{team} ने ज़्यादा बदलाव नहीं किया"}[lang]
            casual = f"{since}: {same}."
            detail = "; ".join(f"{LABEL[lang][c['measure']]} {value(c['measure'], c['before'], lang, True)} → "
                               f"{value(c['measure'], c['after'], lang, True)}" for c in f["unchanged"])
            analyst = f"{casual[:-1]} ({detail})." if detail else casual
        dw = f.get("did_it_work") or {}
        if dw.get("possession_pct") and f["kind"] == "confirmed":
            b, a = dw["possession_pct"]
            analyst += {"en": f" Possession {b}% → {a}%.", "es": f" Posesión {b}% → {a}%.",
                        "hi": f" पज़ेशन {b}% → {a}%."}[lang]
        out[lang] = {"analyst": analyst, "casual": casual}
    return out


def _shift(f: dict) -> dict:
    team, c, out = f["team_name"], f.get("change") or {}, {}
    for lang in LANGUAGES:
        if c.get("measure") == "player_position":
            who = surname(f.get("player")) or {"en": "A player", "es": "Un jugador", "hi": "एक खिलाड़ी"}[lang]
            casual = {"en": f"{who} takes up a new position for {team}.",
                      "es": f"{who} ocupa una nueva posición en {team}.",
                      "hi": f"{who} ने {team} के लिए नई पोज़ीशन ली।"}[lang]
            analyst = casual
        elif c:
            casual = _change_text(c, team, lang, False) + "."
            analyst = _change_text(c, team, lang, True)
            if f.get("since"):
                analyst += {"en": f" since {f['since']}", "es": f" desde el {f['since']}",
                            "hi": f" ({f['since']} से)"}[lang]
            analyst += "."
        else:
            casual = analyst = {"en": f"{team} are changing their approach.",
                                "es": f"{team} está cambiando su planteamiento.",
                                "hi": f"{team} अपना तरीका बदल रही है।"}[lang]
        if f.get("unusual"):
            analyst += {"en": f" Unusual for {team}.", "es": f" Poco habitual en {team}.",
                        "hi": f" {team} के लिए यह असामान्य है।"}[lang]
        out[lang] = {"analyst": analyst, "casual": casual}
    return out


def _summary(f: dict) -> dict:
    team, out = f["team_name"], {}
    for lang in LANGUAGES:
        head = {"en": f"{team} have made several changes", "es": f"{team} ha hecho varios ajustes",
                "hi": f"{team} ने कई बदलाव किए हैं"}[lang]
        state = _state_text(f.get("state") or {}, lang, True)
        now = {"en": "now", "es": "ahora", "hi": "अब"}[lang]
        out[lang] = {"analyst": f"{head}: {now} {state}." if state else f"{head}.",
                     "casual": f"{head}."}
    return out


def _check_in(f: dict) -> dict:
    out = {}
    teams = f.get("teams") or {}
    for lang in LANGUAGES:
        head = {"en": f"{f['minute']} check-in: {score_line(f)}",
                "es": f"Minuto {f['minute']}: {score_line(f)}",
                "hi": f"{f['minute']} अपडेट: {score_line(f)}"}[lang]
        lines = [(f[s], teams.get(f[s], {}).get("line_height_m")) for s in ("home", "away")]
        if all(v is not None for _, v in lines):
            lab = LABEL[lang]["line_height_m"]
            analyst = f"{head}. {lab.capitalize()}: " + ", ".join(
                f"{club} {value('line_height_m', v, lang, True)}" for club, v in lines)
            press = [(f[s], teams.get(f[s], {}).get("pressing_per_min")) for s in ("home", "away")]
            if all(v is not None for _, v in press):
                analyst += f"; {LABEL[lang]['pressing_per_min']}: " + ", ".join(
                    f"{club} {value('pressing_per_min', v, lang, True)}" for club, v in press)
            analyst += "."
        else:
            analyst = head + "."
        out[lang] = {"analyst": analyst, "casual": head + "."}
    return out


def _external(f: dict) -> dict:
    out = {}
    for lang in LANGUAGES:
        if f["reason"] == "conditions" and f.get("conditions"):
            c = f["conditions"]
            w = WEATHER[lang].get(c.get("weather"), c.get("weather", ""))
            casual = {"en": f"Conditions change: {w}.", "es": f"Cambian las condiciones: {w}.",
                      "hi": f"मौसम बदला: {w}।"}[lang]
            analyst = casual
            if c.get("temperature_c") is not None:
                analyst = {"en": f"Conditions change: {w}, {c['temperature_c']}°C.",
                           "es": f"Cambian las condiciones: {w}, {c['temperature_c']} °C.",
                           "hi": f"मौसम बदला: {w}, {c['temperature_c']}°C।"}[lang]
        else:
            casual = {"en": f"Final stretch ({f['minute']}): {score_line(f)}.",
                      "es": f"Recta final ({f['minute']}): {score_line(f)}.",
                      "hi": f"आख़िरी मिनट ({f['minute']}): {score_line(f)}।"}[lang]
            analyst = casual
        out[lang] = {"analyst": analyst, "casual": casual}
    return out


WRITERS = {"expect": _expect, "confirmed": _confirmed, "retracted": _confirmed, "shift": _shift,
           "summary": _summary, "check_in": _check_in, "external": _external}


def captions(f: dict) -> dict[str, str]:
    """{viewer_type}.{language} → caption, 12 in all."""
    by_lang = WRITERS[f["kind"]](f)
    # Whose moment it is: the scorer for a goal, otherwise the trigger's team
    subject = (f.get("event") or {}).get("team") or f.get("team")
    out = {}
    for lang in LANGUAGES:
        base = by_lang[lang]
        out[f"analyst.{lang}"] = base["analyst"]
        out[f"casual.{lang}"] = base["casual"]
        for side in ("home", "away"):
            text = base["casual"]
            if subject and subject != f[side]:
                text = f"{OPPONENTS[lang]}: {text}"
            out[f"supporter_{side}.{lang}"] = text
    # Hindi sentences end with a danda; decimal points stay
    for key in [k for k in out if k.endswith(".hi")]:
        out[key] = re.sub(r"\.(?=\s|$)", "।", out[key])
    return out


def core_text(f: dict) -> str:
    """The English analyst sentence, used as the insight's `text_en_core`."""
    return WRITERS[f["kind"]](f)["en"]["analyst"]
