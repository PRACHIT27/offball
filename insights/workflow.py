"""One workflow run per trigger (LLD §2, §5, §8, §9).

Coordinator (code) → tactics agents in parallel → shift explainer → storyteller → checker, with
up to 2 rewrites. A caption that still fails, or anything missing when the deadline fires, falls
back to its template caption (IG-25), so nothing ungrounded ever goes on air.
"""

import asyncio
import json
import re
import time

from insights import checker, facts, templates
from insights.agents import FAST, RUN, RunContext, Team
from insights.data import MatchData
from insights.models import Checker, Insight

DEADLINE_S = {"expect": 8.0, "default": 20.0}  # IG-30
MAX_REWRITES = 2
KEYS = [f"{v}.{lang}" for lang in templates.LANGUAGES for v in templates.VIEWER_TYPES]


def plan(f: dict) -> dict:
    """The coordinator: which tactics agents run, and the deadline (LLD §5 table)."""
    if f["kind"] == "expect":
        # Deviation from LLD §5: no tactics agents for expect. They take 6–8 s and the 8 s
        # deadline can't fit them; the trigger already carries the team's current state, and the
        # tactics agents check the prediction at confirm-due time.
        sides = []
    elif f["trigger_type"] == "check_in":
        sides = ["home", "away"]
    elif f.get("team"):
        sides = ["home" if f["team"] == f["home"] else "away"]
    else:
        sides = []
    # Expect captions must be on air within 8 s: one tool call per tactics agent
    return {"tactics": sides, "deadline_s": DEADLINE_S.get(f["kind"], DEADLINE_S["default"]),
            "tactics_budget": 1 if f["kind"] == "expect" else 2}


def _json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _brief(f: dict) -> str:
    """The facts as the agents see them: no trigger internals they can't use."""
    keep = {k: v for k, v in f.items() if k not in ("trigger_id", "play_ms", "at_ms")}
    return json.dumps(keep, ensure_ascii=False)


async def _tactics(team: Team, side: str, f: dict) -> dict:
    club = f[side]
    r = await team.tactics[side].run(
        f"Current minute: {f['minute']}. Your team: {club} ({f[side + '_name']}, {side}).\n"
        f"Facts: {_brief(f)}", options=FAST)
    return _json(r.text)


async def _explain(team: Team, f: dict, findings: list[dict]) -> dict:
    r = await team.explainer.run(
        f"Insight kind: {f['kind']}. Current minute: {f['minute']}.\nFacts: {_brief(f)}\n"
        f"Findings from the tactics agents: {json.dumps(findings, ensure_ascii=False)}",
        options=FAST)
    return _json(r.text)


async def _story_lang(team: Team, f: dict, insight: str, findings: list[dict], lang: str) -> dict:
    r = await team.storyteller.run(
        f"Language: {lang}. Keys: {', '.join(f'{v}.{lang}' for v in templates.VIEWER_TYPES)}.\n"
        f"Insight ({f['kind']}): {insight}\nHome club: {f['home_name']} ({f['home']}). "
        f"Away club: {f['away_name']} ({f['away']}). Minute: {f['minute']}. "
        f"Score: {f['home_name']} {f['score']['home']}–{f['score']['away']} {f['away_name']}.\n"
        f"Facts: {_brief(f)}\nFindings: {json.dumps(findings, ensure_ascii=False)}",
        options=FAST)
    return _json(r.text)


async def _story(team: Team, f: dict, insight: str, findings: list[dict]) -> dict:
    """One storyteller call per language, in parallel: three short answers beat one long one."""
    parts = await asyncio.gather(*(_story_lang(team, f, insight, findings, lang)
                                   for lang in templates.LANGUAGES), return_exceptions=True)
    return {k: v for part in parts if isinstance(part, dict) for k, v in part.items()}


async def _rewrite(team: Team, f: dict, insight: str, captions: dict, failed: dict) -> dict:
    asks = "\n".join(f"- {k}: \"{captions.get(k, '')}\" failed because: {'; '.join(v)}"
                     for k, v in failed.items())
    r = await team.storyteller.run(
        f"Insight ({f['kind']}): {insight}\nFacts: {_brief(f)}\nThese captions failed the "
        f"checker. Rewrite only these keys, in their own language, using only numbers from the "
        f"insight and facts:\n{asks}", options=FAST)
    return _json(r.text)


class _Progress:
    """What a run has so far, so a deadline keeps everything that already passed."""

    def __init__(self):
        self.core: str | None = None
        self.evidence: dict = {}
        self.captions: dict[str, str] = {}
        self.passed: set[str] = set()
        self.attempts = 0
        self.reasons: list[str] = []


async def _agents(team: Team, f: dict, p: dict, run: RunContext, out: _Progress) -> None:
    run.budgets.update({f"tactics_{s}": p["tactics_budget"] for s in p["tactics"]})
    findings = await asyncio.gather(*(_tactics(team, s, f) for s in p["tactics"]),
                                    return_exceptions=True)
    findings = [x for x in findings if isinstance(x, dict)]
    ex = await _explain(team, f, findings)
    g = checker.Grounding(f, run.tool_results)
    core_reasons = checker.check_caption("analyst.en", ex.get("text", ""), g)
    if core_reasons:
        out.reasons += [f"core: {r}" for r in core_reasons]
    else:
        out.core = ex["text"]
        out.evidence = {"event_ids": ex.get("event_ids") or [],
                        "window_ids": ex.get("window_ids") or []}
    insight = out.core or templates.core_text(f)
    out.captions = {k: v for k, v in (await _story(team, f, insight, findings)).items()
                    if k in KEYS and isinstance(v, str)}
    for attempt in range(MAX_REWRITES + 1):
        out.attempts = attempt + 1
        g = checker.Grounding(f, run.tool_results)
        failed = {k: checker.check_caption(k, out.captions.get(k, ""), g) or
                  ([] if out.captions.get(k) else ["missing"]) for k in KEYS}
        failed = {k: v for k, v in failed.items() if v}
        if team.safety:
            clean = {k: out.captions[k] for k in KEYS if k not in failed}
            try:
                for k, v in (await team.safety.review(clean, g)).items():
                    if v:
                        failed[k] = v
            except Exception as e:  # unverified captions never go on air
                failed.update({k: [f"safety check unavailable: {type(e).__name__}"]
                               for k in clean})
        out.passed = set(KEYS) - set(failed)
        if not failed or attempt == MAX_REWRITES:
            out.reasons += [f"{k}: {'; '.join(v)}" for k, v in failed.items()]
            return
        fixed = await _rewrite(team, f, insight, out.captions, failed)
        out.captions.update({k: v for k, v in fixed.items() if k in failed and isinstance(v, str)})


async def run_trigger(trigger: dict, data: MatchData, team: Team) -> Insight:
    t0 = time.perf_counter()
    f = facts.build(trigger, data)
    p = plan(f)
    run = RunContext(as_of=(f["period"], f["at_ms"]))
    RUN.set(run)
    out = _Progress()
    try:
        async with asyncio.timeout(p["deadline_s"]):
            await _agents(team, f, p, run, out)
    except TimeoutError:
        out.reasons.append(f"deadline {p['deadline_s']:g} s")
    except Exception as e:  # model quota or error: templates (LLD §9)
        out.reasons.append(f"error: {type(e).__name__}: {e}"[:300])

    fallback = templates.captions(f)
    captions = {k: out.captions[k] if k in out.passed else fallback[k] for k in KEYS}
    template_keys = [k for k in KEYS if k not in out.passed]
    evidence = {k: sorted(set(f["evidence"][k]) | set(out.evidence.get(k, [])))
                for k in ("event_ids", "window_ids")}
    return Insight(
        insight_id=trigger["trigger_id"].replace("t-", "i-"), trigger_id=trigger["trigger_id"],
        match_id=data.match_id, kind=f["kind"], period=f["period"], at_ms=f["at_ms"],
        play_ms=f["play_ms"], team_id=f["team"],
        text_en_core=out.core or templates.core_text(f), captions=captions, evidence=evidence,
        caption_source="template" if len(template_keys) == len(KEYS) else "agent",
        checker=Checker(attempts=out.attempts, passed=not template_keys, reasons=out.reasons,
                        template_keys=template_keys),
        latency_ms=round((time.perf_counter() - t0) * 1000),
        tool_calls=[r["tool"] for r in run.tool_results])
