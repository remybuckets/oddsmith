"""Tool registry: what Claude is offered, and the one entry point that runs a tool call."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from orchestrator.tools import (
    compare_to_market,
    get_availability,
    get_fixtures,
    get_head_to_head,
    get_league_table,
    get_odds,
    get_odds_movement,
    get_player_stats,
    get_team_stats,
    resolve_entity,
)
from orchestrator.tools.context import ToolContext
from orchestrator.tools.contract import output_problem, tool_specs, validate_input
from orchestrator.tools.envelope import ToolError, error_envelope

logger = logging.getLogger(__name__)

Runner = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]

RUNNERS: dict[str, Runner] = {
    "resolve_entity": resolve_entity.run,
    "get_player_stats": get_player_stats.run,
    "get_team_stats": get_team_stats.run,
    "get_head_to_head": get_head_to_head.run,
    "get_fixtures": get_fixtures.run,
    "get_league_table": get_league_table.run,
    "get_availability": get_availability.run,
    "get_odds": get_odds.run,
    "get_odds_movement": get_odds_movement.run,
    "compare_to_market": compare_to_market.run,
}

# Not offered to Claude while NEWS_ENABLED=false (DECISIONS.md #5).
NEWS_TOOLS = frozenset({"search_news"})

INTERNAL_ERROR_MESSAGE = "Something went wrong fetching that data. Try again or rephrase."


def is_offered(name: str, *, news_enabled: bool) -> bool:
    return news_enabled or name not in NEWS_TOOLS


def tool_definitions(*, news_enabled: bool) -> list[dict[str, Any]]:
    """The tool list sent to Claude: implemented, offered tools, contract fields only."""
    return [
        {"name": name, "description": spec["description"], "input_schema": spec["input_schema"]}
        for name, spec in tool_specs().items()
        if name in RUNNERS and is_offered(name, news_enabled=news_enabled)
    ]


async def run_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validate input, run the tool and check its output. Always returns an envelope."""
    runner = RUNNERS.get(name)
    if runner is None or name not in tool_specs():
        return error_envelope(ToolError("unsupported", f"Tool {name} is not available."))
    try:
        result = await runner(ctx, validate_input(name, args))
    except ToolError as error:
        return error_envelope(error)
    except Exception:
        logger.exception("tool %s failed with input %r", name, args)
        return error_envelope(ToolError("internal", INTERNAL_ERROR_MESSAGE))

    problem = output_problem(name, result)
    if problem is not None:
        logger.error("tool %s broke its output contract: %s", name, problem)
        return error_envelope(ToolError("internal", INTERNAL_ERROR_MESSAGE))
    return result
