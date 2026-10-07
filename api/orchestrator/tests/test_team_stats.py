import pytest

from orchestrator.tests.seed import BRE, MCI
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio


async def team_stats(ctx, **args):
    return await run_tool(ctx, "get_team_stats", args)


async def test_season_summary_answers_over_2_5_question(ctx):
    result = await team_stats(ctx, team_id=BRE)

    assert result["ok"] is True
    data = result["data"]
    assert data["team"] == {"id": BRE, "name": "Brentford"}
    assert (data["played"], data["won"], data["drawn"], data["lost"]) == (3, 0, 1, 2)
    assert data["form"] == "LDL"
    assert (data["goals_for"], data["goals_against"]) == (4, 7)
    assert (data["xg_for"], data["xg_against"]) == (4.5, 7.2)
    assert data["over_2_5"] == {"count": 3, "of": 3, "pct": 100.0}
    assert data["btts"] == {"count": 3, "of": 3, "pct": 100.0}
    assert data["clean_sheets"] == {"count": 0, "of": 3, "pct": 0.0}
    assert data["corners_per_match"] == 4.67
    assert data["cards_per_match"] == 2.67
    assert [m["fixture_id"] for m in data["matches"]] == [101, 105, 108]
    assert data["matches"][0] == {
        "fixture_id": 101,
        "kickoff_at": "2026-08-22T14:00:00Z",
        "opponent": "Arsenal",
        "venue": "away",
        "goals_for": 1,
        "goals_against": 2,
        "xg_for": 1.2,
        "xg_against": 2.1,
        "result": "L",
    }


async def test_fresh_rows(ctx):
    result = await team_stats(ctx, team_id=BRE)

    assert result["as_of"] == "2026-10-06T06:00:00Z"
    assert result["is_stale"] is False
    assert result["warnings"] == []


async def test_home_split(ctx):
    result = await team_stats(ctx, team_id=BRE, venue="home")

    assert result["data"]["played"] == 1
    assert result["data"]["form"] == "D"
    assert result["data"]["filters"] == {"season": "2026/27", "venue": "home", "last_n": None}


async def test_last_n(ctx):
    result = await team_stats(ctx, team_id=BRE, last_n=1)
    assert [m["fixture_id"] for m in result["data"]["matches"]] == [108]


async def test_stale_rows_and_missing_xg_are_flagged(ctx):
    result = await team_stats(ctx, team_id=MCI)

    assert result["is_stale"] is True
    assert result["as_of"] == "2026-10-04T00:00:00Z"
    assert result["warnings"] == ["xG missing for 1 of 3 matches"]
    assert result["data"]["xg_for"] == 5.1


async def test_no_matches_is_no_data(ctx):
    result = await team_stats(ctx, team_id=BRE, season="2025/26")
    assert result["error"]["code"] == "no_data"
    assert "Brentford" in result["error"]["message"]


async def test_unknown_team_is_not_found(ctx):
    result = await team_stats(ctx, team_id=99999)
    assert result["error"]["code"] == "not_found"
