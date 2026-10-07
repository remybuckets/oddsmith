import pytest

from orchestrator.tests.seed import ARS, AVL, MCGINN, NEW, ROMERO, TOT
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio


async def h2h(ctx, **args):
    return await run_tool(ctx, "get_head_to_head", args)


async def test_meetings_across_seasons_newest_first(ctx):
    result = await h2h(ctx, team_a_id=AVL, team_b_id=TOT)

    assert result["ok"] is True
    data = result["data"]
    assert data["team_a"] == {"id": AVL, "name": "Aston Villa"}
    assert data["team_b"] == {"id": TOT, "name": "Tottenham Hotspur"}
    assert [m["fixture_id"] for m in data["meetings"]] == [102, 301, 302]
    assert data["meetings"][2] == {
        "fixture_id": 302,
        "kickoff_at": "2025-09-20T14:00:00Z",
        "home": "Aston Villa",
        "away": "Tottenham Hotspur",
        "home_score": 2,
        "away_score": 0,
        "total_cards": 6,
    }
    assert "most_booked" not in data


async def test_summary_is_from_team_a_point_of_view(ctx):
    result = await h2h(ctx, team_a_id=AVL, team_b_id=TOT)

    assert result["data"]["summary"] == {
        "played": 3,
        "team_a_wins": 1,
        "draws": 2,
        "team_b_wins": 0,
        "avg_goals": 2.67,
        "over_2_5": {"count": 1, "of": 3, "pct": 33.3},
        "btts": {"count": 2, "of": 3, "pct": 66.7},
    }


async def test_most_booked_players_in_the_fixture(ctx):
    result = await h2h(ctx, team_a_id=AVL, team_b_id=TOT, include_bookings=True)

    booked = result["data"]["most_booked"]
    assert booked == [
        {
            "player": {
                "id": ROMERO,
                "name": "Cristian Romero",
                "team_id": TOT,
                "team_name": "Tottenham Hotspur",
            },
            "appearances": 3,
            "yellow_cards": 2,
            "red_cards": 1,
        },
        {
            "player": {
                "id": MCGINN,
                "name": "John McGinn",
                "team_id": AVL,
                "team_name": "Aston Villa",
            },
            "appearances": 2,
            "yellow_cards": 1,
            "red_cards": 0,
        },
    ]


async def test_limit(ctx):
    result = await h2h(ctx, team_a_id=TOT, team_b_id=AVL, limit=1)

    assert [m["fixture_id"] for m in result["data"]["meetings"]] == [102]
    assert result["data"]["summary"]["played"] == 1


async def test_freshness_fields(ctx):
    result = await h2h(ctx, team_a_id=AVL, team_b_id=TOT, include_bookings=True)

    assert result["source"] == "API-Football"
    assert result["as_of"] == "2026-10-06T06:00:00Z"
    assert result["is_stale"] is False


async def test_teams_that_have_not_met_is_no_data(ctx):
    result = await h2h(ctx, team_a_id=ARS, team_b_id=NEW)
    assert result["error"]["code"] == "no_data"


async def test_same_team_is_invalid(ctx):
    result = await h2h(ctx, team_a_id=ARS, team_b_id=ARS)
    assert result["error"]["code"] == "invalid_input"


async def test_unknown_team_is_not_found(ctx):
    result = await h2h(ctx, team_a_id=ARS, team_b_id=99999)
    assert result["error"]["code"] == "not_found"
