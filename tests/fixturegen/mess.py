"""Mess rules from ingestion LLD §5. Each rule can be switched on alone for its test."""

import copy
import json

from tests.fixturegen.match import Truth
from tests.fixturegen.providers import Msg

LIGHT = frozenset({"a_duplicates", "a_corrections", "a_deletions", "a_clock_offset",
                   "b_dropped", "b_duplicates", "b_noise"})
FULL = LIGHT | {"a_out_of_order", "a_broken", "b_wrong_units"}
LEVELS = {"off": frozenset(), "light": LIGHT, "full": FULL}

PHANTOM_BASE = 900_000


def _events(msgs: list[Msg]) -> list[int]:
    return [i for i, m in enumerate(msgs)
            if isinstance(m.body, dict) and m.body["msgType"] == "event"]


def _pick(rng, items, share: float, minimum: int = 1) -> list:
    n = max(minimum, int(round(len(items) * share)))
    return sorted(rng.choice(items, size=min(n, len(items)), replace=False).tolist())


def apply_feed_a(rules, msgs: list[Msg], truth: Truth, rng, log: dict) -> list[Msg]:
    by_id = {e["event_id"]: e for e in truth.events}
    out = list(msgs)
    positional = [i for i in _events(out) if "x" in out[i].body]

    if "a_corrections" in rules:
        chosen = _pick(rng, positional, 0.03)
        for i in chosen:
            true = out[i]
            wrong = copy.deepcopy(true.body)
            wrong["x"] = round(min(100.0, max(0.0, wrong["x"] + rng.choice([-1, 1])
                                              * rng.uniform(5, 10))), 1)
            true.body["version"] = 2
            out[i] = Msg(true.emitted_ms, "A", wrong, true.tag + ":v1")
            out.append(Msg(true.emitted_ms + rng.uniform(5_000, 60_000), "A", true.body,
                           true.tag + ":v2"))
            by_id[true.tag]["version"] = 2
        log["a_corrections"] = [out[i].tag.split(":")[0] for i in chosen]

    if "a_deletions" in rules:
        sources = _pick(rng, positional, 0.005)
        phantoms = []
        for k, i in enumerate(sources):
            body = copy.deepcopy(out[i].body)
            body["eventId"] = PHANTOM_BASE + k
            body["timeSec"] = round(body["timeSec"] + 0.5, 3)
            emitted = out[i].emitted_ms + 500
            out.append(Msg(emitted, "A", body, f"phantom{k}"))
            out.append(Msg(emitted + rng.uniform(10_000, 60_000), "A",
                           {"msgType": "delete", "matchId": body["matchId"],
                            "eventId": body["eventId"], "version": 2}, f"phantom{k}:delete"))
            phantoms.append(f"e-{PHANTOM_BASE + k:06d}")
        log["a_deletions"] = phantoms

    if "a_duplicates" in rules:
        chosen = _pick(rng, _events(out), 0.02)
        for i in chosen:
            m = out[i]
            out.append(Msg(m.emitted_ms + rng.uniform(100, 2_000), "A", copy.deepcopy(m.body),
                           m.tag + ":dup"))
        log["a_duplicates"] = len(chosen)

    if "a_out_of_order" in rules:
        chosen = _pick(rng, _events(out), 0.05)
        for i in chosen:
            out[i].emitted_ms += rng.uniform(500, 3_000)
        log["a_out_of_order"] = len(chosen)

    if "a_broken" in rules:
        chosen = _pick(rng, [i for i in _events(out) if ":" not in out[i].tag
                             and not out[i].tag.startswith("phantom")], 0.002, minimum=3)
        broken = []
        for n, i in enumerate(chosen):
            body = copy.deepcopy(out[i].body)
            kind = n % 3
            if kind == 0:
                out[i].body = json.dumps(body)[:-7]
            elif kind == 1:
                body["playerId"] = 99_999
                out[i].body = body
            else:
                body["x"] = 150.0
                out[i].body = body
            broken.append(out[i].tag)
        log["a_broken"] = broken

    return out


def apply_feed_b(rules, msgs: list[Msg], rng, log: dict) -> list[Msg]:
    out = list(msgs)

    def droppable(i):
        first = out[i].body["frames"][0]["frameIdx"] - out[i].body["periodStartFrame"]
        return first >= 50  # keep each period's kickoff for clock alignment

    if "b_dropped" in rules:
        candidates = [i for i in range(len(out)) if droppable(i)]
        drop = set(_pick(rng, candidates, 0.005))
        p1 = [i for i in candidates if out[i].body["periodId"] == 1]
        g0 = p1[len(p1) // 3 + int(rng.integers(0, len(p1) // 3))]
        gap = set(range(g0, g0 + 10))  # 10 batches × 5 frames = 2 s
        log["b_dropped"] = sorted(out[i].body["batchSeq"] for i in drop - gap)
        log["b_gap"] = {"period": 1,
                        "first_frame": out[g0].body["frames"][0]["frameIdx"]
                        - out[g0].body["periodStartFrame"], "frames": 50}
        out = [m for i, m in enumerate(out) if i not in drop | gap]

    if "b_duplicates" in rules:
        chosen = _pick(rng, list(range(len(out))), 0.01)
        for i in chosen:
            m = out[i]
            out.append(Msg(m.emitted_ms + rng.uniform(50, 1_000), "B", copy.deepcopy(m.body),
                           m.tag + ":dup"))
        log["b_duplicates"] = len(chosen)

    if "b_wrong_units" in rules:
        chosen = _pick(rng, [i for i in range(len(out)) if ":" not in out[i].tag], 0, minimum=3)
        for i in chosen:
            for fr in out[i].body["frames"]:
                fr["ball"] = [v * 100 for v in fr["ball"][:2]] + [fr["ball"][2]]
                for side in ("home", "away"):
                    fr[side] = [[s, x * 100, y * 100] for s, x, y in fr[side]]
        log["b_wrong_units"] = [out[i].body["batchSeq"] for i in chosen]

    return out


def pause(msgs: list[Msg], start_ms: float, duration_ms: float) -> list[Msg]:
    """Feed stops sending for a while (LLD §11 feed-stop test); messages in the window are lost."""
    return [m for m in msgs if not start_ms <= m.emitted_ms < start_ms + duration_ms]


def rules_for(level: str, extra=(), without=()) -> frozenset:
    return (LEVELS[level] | frozenset(extra)) - frozenset(without)
