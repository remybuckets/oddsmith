import pytest

from orchestrator.tests.seed import ARS, AVL, TOT
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio


async def fixtures(ctx, **args):
    return await run_tool(ctx, "get_fixtures", args)


def ids(result):
    return [f["fixture_id"] for f in result["data"]["fixtures"]]


async def test_next_meeting_between_two_teams(ctx):
    result = await fixtures(ctx, team_id=AVL, opponent_team_id=TOT, status="scheduled")

    assert result["ok"] is True
    assert result["data"]["fixtures"] == [
        {
            "fixture_id": 201,
            "matchweek": 7,
            "kickoff_at": "2026-10-17T14:00:00Z",
            "status": "scheduled",
            "home": {"id": AVL, "name": "Aston Villa"},
            "away": {"id": TOT, "name": "Tottenham Hotspur"},
            "home_score": None,
            "away_score": None,
        }
    ]
    assert result["as_of"] == "2026-10-07T06:00:00Z"
    assert result["freshness_limit_hours"] == 48


async def test_matchweek_listing_is_in_kickoff_order(ctx):
    result = await fixtures(ctx, matchweek=7)
    assert ids(result) == [201, 202, 203]


async def test_finished_takes_latest_results_in_kickoff_order(ctx):
    result = await fixtures(ctx, team_id=ARS, status="finished", limit=2)

    assert ids(result) == [104, 107]
    assert result["data"]["fixtures"][1]["home_score"] == 1


async def test_all_status_picks_matches_nearest_now(ctx):
    result = await fixtures(ctx, team_id=ARS, limit=2)
    assert ids(result) == [107, 203]


async def test_date_window_uses_uk_calendar_days(ctx):
    result = await fixtures(ctx, date_from="2026-10-17", date_to="2026-10-17")
    assert ids(result) == [201, 202]


async def test_only_current_season(ctx):
    result = await fixtures(ctx, team_id=AVL, opponent_team_id=TOT, status="finished")
    assert ids(result) == [102]


async def test_nothing_matching_is_no_data(ctx):
    result = await fixtures(ctx, matchweek=38)
    assert result["error"]["code"] == "no_data"


async def test_reversed_dates_are_invalid(ctx):
    result = await fixtures(ctx, date_from="2026-10-18", date_to="2026-10-17")
    assert result["error"]["code"] == "invalid_input"


async def test_same_team_twice_is_invalid(ctx):
    result = await fixtures(ctx, team_id=AVL, opponent_team_id=AVL)
    assert result["error"]["code"] == "invalid_input"
