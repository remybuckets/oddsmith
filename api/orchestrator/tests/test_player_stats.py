import pytest

from orchestrator.tests.seed import BRE, JESUS, SAKA
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio


async def player_stats(ctx, **args):
    return await run_tool(ctx, "get_player_stats", args)


async def test_season_totals_per90_and_matches(ctx):
    result = await player_stats(ctx, player_id=SAKA)

    assert result["ok"] is True
    data = result["data"]
    assert data["player"] == {
        "id": SAKA,
        "name": "Bukayo Saka",
        "team_id": 1,
        "team_name": "Arsenal",
    }
    assert data["appearances"] == 3
    assert data["minutes"] == 265
    totals = data["totals"]
    assert (totals["goals"], totals["assists"], totals["shots"]) == (2, 2, 9)
    assert totals["shots_on_target"] == 4
    assert totals["xg"] == 1.2
    assert totals["xa"] == 0.8
    assert (totals["yellow_cards"], totals["red_cards"]) == (1, 0)
    assert data["per90"]["goals"] == 0.68
    assert data["per90"]["xa"] == 0.27
    assert [m["fixture_id"] for m in data["matches"]] == [101, 104, 107]
    assert [m["opponent"] for m in data["matches"]] == [
        "Brentford",
        "Tottenham Hotspur",
        "Aston Villa",
    ]


async def test_missing_xg_is_warned_and_per90_uses_known_minutes(ctx):
    result = await player_stats(ctx, player_id=SAKA)

    assert result["warnings"] == ["xG missing for 1 of 3 matches"]
    # 1.20 xG over the 175 minutes that have xG
    assert result["data"]["per90"]["xg"] == 0.62
    assert result["data"]["matches"][2]["xg"] is None


async def test_freshness_fields(ctx):
    result = await player_stats(ctx, player_id=SAKA)

    assert result["source"] == "API-Football"
    assert result["as_of"] == "2026-10-06T06:00:00Z"
    assert result["freshness_limit_hours"] == 48
    assert result["is_stale"] is False


async def test_away_split(ctx):
    result = await player_stats(ctx, player_id=SAKA, venue="away")

    data = result["data"]
    assert (data["appearances"], data["minutes"], data["totals"]["goals"]) == (1, 85, 1)
    assert data["per90"]["goals"] == 1.06
    assert data["matches"][0]["venue"] == "away"
    assert result["warnings"] == []
    assert data["filters"] == {
        "season": "2026/27",
        "venue": "away",
        "last_n": None,
        "opponent_team_id": None,
    }


async def test_last_n_takes_most_recent_appearances(ctx):
    result = await player_stats(ctx, player_id=SAKA, last_n=2)
    assert [m["fixture_id"] for m in result["data"]["matches"]] == [104, 107]


async def test_opponent_split(ctx):
    result = await player_stats(ctx, player_id=SAKA, opponent_team_id=BRE)
    assert [m["fixture_id"] for m in result["data"]["matches"]] == [101]


async def test_zero_minute_rows_are_not_appearances(ctx):
    result = await player_stats(ctx, player_id=JESUS)
    assert result["error"]["code"] == "no_data"
    assert "Gabriel Jesus" in result["error"]["message"]


async def test_other_season_with_no_rows_is_no_data(ctx):
    result = await player_stats(ctx, player_id=SAKA, season="2025/26")
    assert result["error"]["code"] == "no_data"


async def test_unknown_player_is_not_found(ctx):
    result = await player_stats(ctx, player_id=99999)
    assert result["error"]["code"] == "not_found"
