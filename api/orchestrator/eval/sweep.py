"""Tools against SQL across the whole database, without Claude: every team, the players
who have played, every pairing, matchweek and priced fixture. Free to run, and far wider
than 50 questions, so it catches a wrong tool figure the eval set happens not to ask for."""

from collections import Counter
from datetime import datetime
from itertools import combinations
from typing import Any

import asyncpg

from orchestrator.eval.oracle import verify
from orchestrator.tools import run_tool
from orchestrator.tools.context import ToolContext

SEASON, LAST_SEASON = "2026/27", "2025/26"
MATCHWEEKS = range(1, 39)
MOVEMENT_HOURS = (48, 168)
SELECTIONS = {"h2h": ("home", "draw", "away"), "totals": ("over", "under"), "btts": ("yes", "no")}
MAX_PROBLEMS = 200

_TEAMS_SQL = """
SELECT DISTINCT t.id FROM teams t JOIN fixtures f ON t.id IN (f.home_id, f.away_id)
WHERE f.season = $1 ORDER BY t.id
"""
_PLAYERS_SQL = """
SELECT pms.player_id
FROM player_match_stats pms JOIN fixtures f ON f.id = pms.fixture_id
WHERE f.season = $1 AND f.status = 'finished' AND pms.minutes > 0
GROUP BY pms.player_id ORDER BY count(*) DESC, pms.player_id LIMIT $2
"""
_MARKETS_SQL = """
SELECT DISTINCT o.fixture_id, o.market, o.line, f.status
FROM odds_snapshots o JOIN fixtures f ON f.id = o.fixture_id
ORDER BY o.fixture_id, o.market
"""


def _market_args(row: asyncpg.Record) -> dict[str, Any]:
    line = {} if row["line"] is None else {"line": float(row["line"])}
    return {"fixture_id": row["fixture_id"], "market": row["market"], **line}


def _team_calls(teams: list[int], last_season_teams: list[int]) -> list[tuple[str, dict]]:
    this_season = [
        ("get_team_stats", {"team_id": team, **split})
        for team in teams
        for split in ({}, {"venue": "home"}, {"venue": "away"}, {"last_n": 5})
    ]
    last_season = [
        ("get_team_stats", {"team_id": team, "season": LAST_SEASON}) for team in last_season_teams
    ]
    fixtures = [
        ("get_fixtures", {"team_id": team, "status": status, "limit": 5})
        for team in teams
        for status in ("scheduled", "finished")
    ]
    availability = [("get_availability", {"team_id": team}) for team in teams]
    pairings = [
        ("get_head_to_head", {"team_a_id": a, "team_b_id": b, "include_bookings": True})
        for a, b in combinations(teams, 2)
    ]
    return [*this_season, *last_season, *fixtures, *availability, *pairings]


def _player_calls(players: list[int], last_season_players: list[int]) -> list[tuple[str, dict]]:
    this_season = [
        ("get_player_stats", {"player_id": player, **split})
        for player in players
        for split in ({}, {"venue": "away"}, {"last_n": 5})
    ]
    last_season = [
        ("get_player_stats", {"player_id": player, "season": LAST_SEASON})
        for player in last_season_players
    ]
    return [*this_season, *last_season]


def _market_calls(markets: list[asyncpg.Record]) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for row in markets:
        args = _market_args(row)
        movement = [
            ("get_odds_movement", {**args, "selection": selection, "hours": hours})
            for selection in SELECTIONS[row["market"]]
            for hours in MOVEMENT_HOURS
        ]
        value = [("compare_to_market", args)] if row["status"] == "scheduled" else []
        calls = [*calls, ("get_odds", args), *movement, *value]
    fixture_ids = sorted({row["fixture_id"] for row in markets})
    return [*calls, *(("get_availability", {"fixture_id": f}) for f in fixture_ids)]


async def sweep_calls(conn: asyncpg.Connection, max_players: int) -> list[tuple[str, dict]]:
    teams = [r["id"] for r in await conn.fetch(_TEAMS_SQL, SEASON)]
    last_season_teams = [r["id"] for r in await conn.fetch(_TEAMS_SQL, LAST_SEASON)]
    players = [r["player_id"] for r in await conn.fetch(_PLAYERS_SQL, SEASON, max_players)]
    old_players = [r["player_id"] for r in await conn.fetch(_PLAYERS_SQL, LAST_SEASON, max_players)]
    markets = await conn.fetch(_MARKETS_SQL)
    return [
        *(("get_league_table", {"venue": venue}) for venue in ("all", "home", "away")),
        *(("get_fixtures", {"matchweek": matchweek, "limit": 20}) for matchweek in MATCHWEEKS),
        *_team_calls(teams, last_season_teams),
        *_player_calls(players, old_players),
        *_market_calls(markets),
    ]


async def run_sweep(conn: asyncpg.Connection, now: datetime, max_players: int) -> dict[str, Any]:
    """Run every sweep call and verify it. Returns counts per tool and the problems found:
    oracle mismatches, and tool errors with code `internal` (a crash or a broken contract)."""
    calls = await sweep_calls(conn, max_players)
    ctx = ToolContext(conn=conn, now=now)
    outcomes: Counter[tuple[str, str]] = Counter()
    problems: list[str] = []
    for name, args in calls:
        result = await run_tool(ctx, name, args)
        outcome = "ok" if result["ok"] else result["error"]["code"]
        found = await verify(conn, now, {"name": name, "input": args, "result": result})
        if outcome == "internal":
            found = [*found, "tool failed with an internal error"]
        outcomes[name, outcome if not found else "mismatch"] += 1
        problems = [*problems, *(f"{name} {args}: {p}" for p in found)]
    by_tool: dict[str, dict[str, int]] = {}
    for (name, outcome), count in sorted(outcomes.items()):
        by_tool = {**by_tool, name: {**by_tool.get(name, {}), outcome: count}}
    return {
        "calls": len(calls),
        "by_tool": by_tool,
        "problem_count": len(problems),
        "problems": problems[:MAX_PROBLEMS],
    }
