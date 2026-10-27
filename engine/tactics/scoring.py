MEASURE_OF = {"line_height_m": "line_height_m", "pressers": "pressing_per_min",
              "press_distance_m": "pressing_per_min", "formation": "formation_out",
              "pass_length_pref": "style_dial", "tempo_s": "style_dial"}
DETECTABLE = {"line_height_m": 4.0, "pressers": 1, "press_distance_m": 3.0,
              "pass_length_pref": 0.25, "tempo_s": 0.4}


def truth_changes(answer_key: dict) -> list[dict]:
    out = []
    for ch in answer_key.get("tactic_changes", []):
        measures = set()
        for k, after in ch["after"].items():
            before = ch["before"].get(k)
            if k == "formation":
                if before != after:
                    measures.add("formation_out")
            elif k in DETECTABLE and before is not None and abs(after - before) >= DETECTABLE[k]:
                measures.add(MEASURE_OF[k])
        for m in measures:
            out.append({"team_id": ch["team_id"], "measure": m, "period": ch["period"],
                        "at_ms": ch["at_clock_ms"], "cause": ch["cause"].get("rule")})
    return out


def score(answer_key: dict, notes: list[dict], late_window_s: float = 360.0) -> dict:
    truth = truth_changes(answer_key)
    detected = [n for n in notes if n["level"] == "confirmed" and n["change"] in
                ("line_height_m", "pressing_per_min", "style_dial", "formation_out")]
    used: set[str] = set()
    found = []
    for t in truth:
        match = None
        for n in detected:
            if n["note_id"] in used or n["team_id"] != t["team_id"] or n["change"] != t["measure"]:
                continue
            if n["since_period"] != t["period"]:
                continue
            lag = (n["since_ms"] - t["at_ms"]) / 1000
            if -30 <= lag <= late_window_s:
                match = (n, lag)
                break
        if match:
            used.add(match[0]["note_id"])
            found.append({**t, "note_id": match[0]["note_id"], "lag_s": round(match[1])})
    false_alarms = [n for n in detected if n["note_id"] not in used]
    lags = [f["lag_s"] for f in found]
    return {"true_changes": len(truth), "found": len(found),
            "missed": [t for t in truth if not any(f["team_id"] == t["team_id"]
                                                    and f["measure"] == t["measure"]
                                                    and f["at_ms"] == t["at_ms"] for f in found)],
            "false_alarms": len(false_alarms),
            "average_lag_s": round(sum(lags) / len(lags)) if lags else None,
            "matches": found}
