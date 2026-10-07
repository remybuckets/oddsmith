import pytest

from orchestrator.tests.seed import ARS, AVL, BRE, MCI, NEW, TOT
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio


async def table(ctx, **args):
    return await run_tool(ctx, "get_league_table", args)


def order(result):
    return [row["team"]["id"] for row in result["data"]["rows"]]


async def test_table_sorted_by_points_then_goal_difference(ctx):
    result = await table(ctx)

    assert result["ok"] is True
    assert result["data"]["venue"] == "all"
    assert order(result) == [MCI, ARS, TOT, NEW, AVL, BRE]
    assert result["data"]["rows"][0] == {
        "position": 1,
        "team": {"id": MCI, "name": "Manchester City"},
        "played": 3,
        "won": 2,
        "drawn": 1,
        "lost": 0,
        "goals_for": 7,
        "goals_against": 3,
        "goal_difference": 4,
        "points": 7,
        "form": "WDW",
    }
    assert [row["position"] for row in result["data"]["rows"]] == [1, 2, 3, 4, 5, 6]


async def test_home_table_breaks_ties_on_goals_scored(ctx):
    result = await table(ctx, venue="home")
    assert order(result) == [ARS, MCI, TOT, NEW, BRE, AVL]


async def test_table_is_stale_if_any_rows_are(ctx):
    result = await table(ctx)

    assert result["is_stale"] is True
    assert result["as_of"] == "2026-10-04T00:00:00Z"
    assert result["freshness_limit_hours"] == 48


async def test_no_finished_matches_is_no_data(ctx, conn):
    await conn.execute("UPDATE fixtures SET status = 'scheduled' WHERE season = '2026/27'")

    result = await table(ctx)
    assert result["error"]["code"] == "no_data"
