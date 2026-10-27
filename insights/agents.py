"""The agent team (LLD §5) on Microsoft Agent Framework, with numbers only from the MCP stats
server (IG-4).

Each run sets a RunContext. The `pin_as_of` middleware reads it on every tool call: it overwrites
`as_of` with the trigger's moment (IG-6), stops an agent past its tool budget, and records every
tool result so the checker can ground the captions' numbers in them (IG-22).
"""

import contextvars
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agent_framework import Agent, FunctionInvocationContext, MCPStdioTool, function_middleware
from agent_framework.openai import OpenAIChatClient

PROMPTS = Path(__file__).parent / "prompts"
ENDPOINT = os.environ.get("AZURE_AI_ENDPOINT", "https://offball-ai-kr2610.cognitiveservices.azure.com/")
MODEL = os.environ.get("AZURE_AI_MODEL", "gpt-5-mini")
FAST = {"reasoning": {"effort": "minimal"}}

TEAM_TOOLS = ["get_line_height", "get_pressing", "get_style", "get_formation", "compare_periods",
              "get_normal_style", "get_passing_network", "get_chance_routes", "get_recent_events"]
EXPLAINER_TOOLS = ["compare_periods", "get_normal_style"]
MAX_CALLS = {"tactics": 2, "explainer": 2}


@dataclass
class RunContext:
    as_of: tuple[int, int]
    tool_results: list[dict] = field(default_factory=list)
    calls: dict[str, int] = field(default_factory=dict)
    # Per-run tool budgets set by the coordinator; agents not listed use their default
    budgets: dict[str, int] = field(default_factory=dict)


RUN: contextvars.ContextVar[RunContext] = contextvars.ContextVar("insight_run")


def _text(result) -> str:
    if isinstance(result, list):
        return "".join(getattr(c, "text", None) or "" for c in result)
    return str(result)


def pin_as_of(agent: str, budget: int):
    """Middleware for one agent: trigger-time as_of on every call, a tool budget, and a record of
    every tool result for the checker."""

    @function_middleware
    async def middleware(ctx: FunctionInvocationContext, call_next) -> None:
        run = RUN.get()
        used = run.calls.get(agent, 0)
        if used >= run.budgets.get(agent, budget):
            ctx.result = "Tool budget used up: answer now with what you have."
            return
        run.calls[agent] = used + 1
        ctx.arguments["as_of_period"], ctx.arguments["as_of_clock_ms"] = run.as_of
        await call_next()
        text = _text(ctx.result)
        try:
            run.tool_results.append({"tool": ctx.function.name, "result": json.loads(text)})
        except ValueError:
            run.tool_results.append({"tool": ctx.function.name, "result": text})

    return middleware


def prompt(name: str, **kw) -> str:
    return (PROMPTS / f"{name}.md").read_text().replace("{max_calls}", str(kw.get("max_calls", 0)))


class Team:
    """One chat client, the MCP servers and the agents, shared by every run of a match."""

    def __init__(self, data_dir: Path, credential):
        self.client = OpenAIChatClient(model=MODEL, azure_endpoint=ENDPOINT, credential=credential)
        env = {**os.environ, "OFFBALL_MATCH_DATA": str(data_dir)}
        server = [sys.executable, "-m", "mcp_stats.server"]
        self.team_mcp = MCPStdioTool(name="stats", command=server[0], args=server[1:], env=env,
                                     allowed_tools=TEAM_TOOLS)
        self.explainer_mcp = MCPStdioTool(name="stats_compare", command=server[0], args=server[1:],
                                          env=env, allowed_tools=EXPLAINER_TOOLS)

    async def __aenter__(self):
        await self.team_mcp.__aenter__()
        await self.explainer_mcp.__aenter__()
        self.tactics = {side: Agent(self.client, prompt("tactics", max_calls=MAX_CALLS["tactics"]),
                                    name=f"tactics_{side}", tools=self.team_mcp,
                                    middleware=[pin_as_of(f"tactics_{side}", MAX_CALLS["tactics"])])
                        for side in ("home", "away")}
        self.explainer = Agent(self.client, prompt("explainer", max_calls=MAX_CALLS["explainer"]),
                               name="explainer", tools=self.explainer_mcp,
                               middleware=[pin_as_of("explainer", MAX_CALLS["explainer"])])
        self.storyteller = Agent(self.client, prompt("storyteller"), name="storyteller")
        return self

    async def __aexit__(self, *exc):
        await self.explainer_mcp.__aexit__(*exc)
        await self.team_mcp.__aexit__(*exc)
