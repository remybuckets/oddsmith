"""The oracle recomputes each tool's figures from base tables. On correct tool output it
reports nothing; on a tampered figure it reports the mismatch."""

import copy

import pytest

from orchestrator.eval.oracle import verify
from orchestrator.tests.seed import ARS, AVL, NOW, SAKA, TOT
from orchestrator.tools import run_tool

CALLS = [
    ("get_player_stats", {"player_id": SAKA}),
    ("get_player_stats", {"player_id": SAKA, "venue": "away", "last_n": 1}),
    ("get_player_stats", {"player_id": SAKA, "opponent_team_id": AVL}),
    ("get_team_stats", {"team_id": ARS}),
    ("get_team_stats", {"team_id": TOT, "venue": "home", "last_n": 2}),
    ("get_head_to_head", {"team_a_id": AVL, "team_b_id": TOT, "include_bookings": True}),
    ("get_head_to_head", {"team_a_id": TOT, "team_b_id": AVL, "limit": 2}),
    ("get_fixtures", {"team_id": AVL, "status": "scheduled"}),
    ("get_fixtures", {"matchweek": 2}),
    ("get_fixtures", {"date_from": "2026-10-17", "date_to": "2026-10-18", "limit": 2}),
    ("get_league_table", {}),
    ("get_league_table", {"venue": "away"}),
    ("get_availability", {"fixture_id": 201}),
    ("get_availability", {"team_id": ARS}),
    ("get_odds", {"fixture_id": 201, "market": "h2h"}),
    ("get_odds", {"fixture_id": 201, "market": "totals", "line": 2.5}),
    ("get_odds", {"fixture_id": 202, "market": "h2h"}),
    ("get_odds_movement", {"fixture_id": 201, "market": "h2h", "selection": "home"}),
    ("get_odds_movement", {"fixture_id": 201, "market": "h2h", "selection": "away", "hours": 6}),
    ("compare_to_market", {"fixture_id": 201, "market": "h2h"}),
    ("compare_to_market", {"fixture_id": 201, "market": "totals", "line": 2.5}),
    ("resolve_entity", {"query": "Saka"}),
]


async def call(ctx, name, args):
    return {"name": name, "input": args, "result": await run_tool(ctx, name, args)}


@pytest.mark.parametrize(("name", "args"), CALLS, ids=lambda v: str(v))
async def test_oracle_agrees_with_correct_tool_output(ctx, name, args):
    made = await call(ctx, name, args)

    assert made["result"]["ok"], made["result"]
    assert await verify(ctx.conn, NOW, made) == []


def tampered(made, path, value):
    changed = copy.deepcopy(made)
    node = changed["result"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return changed


TAMPERS = [
    ("get_player_stats", {"player_id": SAKA}, ("data", "totals", "goals"), 9),
    ("get_player_stats", {"player_id": SAKA}, ("data", "per90", "shots"), 9.99),
    ("get_player_stats", {"player_id": SAKA}, ("data", "matches", 0, "goals"), 7),
    ("get_team_stats", {"team_id": ARS}, ("data", "won"), 0),
    ("get_team_stats", {"team_id": ARS}, ("data", "over_2_5", "pct"), 99.0),
    ("get_team_stats", {"team_id": ARS}, ("data", "form"), "LLL"),
    ("get_team_stats", {"team_id": ARS}, ("data", "xg_for"), 0.01),
    (
        "get_head_to_head",
        {"team_a_id": AVL, "team_b_id": TOT},
        ("data", "summary", "team_a_wins"),
        9,
    ),
    (
        "get_head_to_head",
        {"team_a_id": AVL, "team_b_id": TOT, "include_bookings": True},
        ("data", "most_booked", 0, "yellow_cards"),
        9,
    ),
    ("get_fixtures", {"matchweek": 2}, ("data", "fixtures", 0, "home_score"), 9),
    (
        "get_fixtures",
        {"matchweek": 7},
        ("data", "fixtures", 0, "kickoff_at"),
        "2026-10-17T15:00:00Z",
    ),
    ("get_league_table", {}, ("data", "rows", 0, "points"), 99),
    ("get_availability", {"team_id": ARS}, ("data", "entries", 0, "status"), "injured"),
    ("get_availability", {"team_id": ARS}, ("data", "entries"), []),
    (
        "get_odds",
        {"fixture_id": 201, "market": "h2h"},
        ("data", "selections", 0, "best_price"),
        9.0,
    ),
    (
        "get_odds",
        {"fixture_id": 201, "market": "h2h"},
        ("data", "selections", 0, "best_bookmaker"),
        "Betfred",
    ),
    ("get_odds", {"fixture_id": 201, "market": "h2h"}, ("as_of",), "2026-10-07T11:00:00Z"),
    ("get_odds", {"fixture_id": 202, "market": "h2h"}, ("is_stale",), False),
    (
        "get_odds_movement",
        {"fixture_id": 201, "market": "h2h", "selection": "home"},
        ("data", "opening_price"),
        9.0,
    ),
    (
        "get_odds_movement",
        {"fixture_id": 201, "market": "h2h", "selection": "home"},
        ("data", "direction"),
        "drift",
    ),
    (
        "compare_to_market",
        {"fixture_id": 201, "market": "h2h"},
        ("data", "selections", 0, "model_probability"),
        0.99,
    ),
    (
        "compare_to_market",
        {"fixture_id": 201, "market": "h2h"},
        ("data", "selections", 0, "edge"),
        0.5,
    ),
    (
        "compare_to_market",
        {"fixture_id": 201, "market": "h2h"},
        ("data", "model", "expected_goals_home"),
        9.9,
    ),
]


@pytest.mark.parametrize(("name", "args", "path", "value"), TAMPERS, ids=lambda v: str(v))
async def test_oracle_reports_a_wrong_figure(ctx, name, args, path, value):
    made = await call(ctx, name, args)

    problems = await verify(ctx.conn, NOW, tampered(made, path, value))

    assert problems, f"oracle missed {path} = {value!r}"


async def test_tool_errors_have_nothing_to_verify(ctx):
    made = await call(ctx, "get_odds", {"fixture_id": 203, "market": "btts"})

    assert not made["result"]["ok"]
    assert await verify(ctx.conn, NOW, made) == []
