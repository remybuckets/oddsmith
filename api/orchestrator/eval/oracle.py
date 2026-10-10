"""Checks a tool result against direct SQL on the base tables.

The tools read the `player_match_rows`, `team_match_rows` and `odds_latest` views and do
their sums in Python. The oracle goes to `fixtures`, `*_match_stats` and `odds_snapshots`
directly and takes results from `fixtures` scores, so a bug in a view, a tool query or a
tool's arithmetic shows up as a mismatch. Read-only: SELECT statements only.
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from orchestrator.eval import oracle_market, oracle_stats
from orchestrator.eval.oracle_common import Expected, iso
from orchestrator.tools.contract import validate_input

Oracle = Callable[
    [asyncpg.Connection, datetime, dict[str, Any], dict[str, Any]], Awaitable[Expected]
]

ORACLES: dict[str, Oracle] = {
    "get_player_stats": oracle_stats.player_stats,
    "get_team_stats": oracle_stats.team_stats,
    "get_head_to_head": oracle_stats.head_to_head,
    "get_fixtures": oracle_stats.fixtures,
    "get_league_table": oracle_stats.league_table,
    "get_availability": oracle_stats.availability,
    "get_odds": oracle_market.odds,
    "get_odds_movement": oracle_market.odds_movement,
    "compare_to_market": oracle_market.compare_to_market,
}

DEFAULT_TOLERANCE = 0.0051  # figures rounded to two decimals


def _differs(got: Any, expected: Any, tolerance: float) -> bool:
    numbers = (int, float)
    if isinstance(got, bool) or isinstance(expected, bool):
        return got is not expected
    if isinstance(got, numbers) and isinstance(expected, numbers):
        return abs(got - expected) > tolerance
    return got != expected


def mismatches(pairs: Iterable[tuple[str, Any, Any] | tuple[str, Any, Any, float]]) -> list[str]:
    """Describe each (label, tool value, SQL value[, tolerance]) that disagrees."""
    problems: list[str] = []
    for label, got, expected, *rest in pairs:
        if _differs(got, expected, rest[0] if rest else DEFAULT_TOLERANCE):
            problems = [*problems, f"{label}: tool says {got!r}, SQL says {expected!r}"]
    return problems


def _envelope_pairs(result: Mapping[str, Any], now: datetime, oldest: datetime) -> list[tuple]:
    limit = result["freshness_limit_hours"]
    is_stale = limit is not None and now - oldest > timedelta(hours=limit)
    return [("as_of", result["as_of"], iso(oldest)), ("is_stale", result["is_stale"], is_stale)]


async def verify(conn: asyncpg.Connection, now: datetime, call: Mapping[str, Any]) -> list[str]:
    """Mismatches between one tool call's result and SQL. `call` is {name, input, result};
    `now` is the time the tool ran at. Failed calls and lookups have nothing to verify."""
    oracle = ORACLES.get(call["name"])
    result = call["result"]
    if oracle is None or not result.get("ok"):
        return []
    args = validate_input(call["name"], dict(call["input"]))
    expected = await oracle(conn, now, args, result["data"])
    return mismatches([*expected.pairs, *_envelope_pairs(result, now, expected.oldest)])
