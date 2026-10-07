import pytest

from orchestrator.tests.seed import BRE, MCGINN, ROMERO, SAKA
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio


async def availability(ctx, **args):
    return await run_tool(ctx, "get_availability", args)


async def test_fixture_lists_both_teams(ctx):
    result = await availability(ctx, fixture_id=201)

    assert result["ok"] is True
    entries = result["data"]["entries"]
    assert [e["player"]["id"] for e in entries] == [MCGINN, ROMERO]
    assert entries[1] == {
        "player": {
            "id": ROMERO,
            "name": "Cristian Romero",
            "team_id": 2,
            "team_name": "Tottenham Hotspur",
        },
        "status": "injured",
        "reason": "Hamstring",
        "expected_return": "2026-10-25",
        "source": "API-Football",
        "updated_at": "2026-10-06T10:00:00Z",
    }


async def test_freshness_is_oldest_of_rows_and_last_successful_sync(ctx):
    result = await availability(ctx, fixture_id=201)

    assert result["source"] == "API-Football"
    assert result["as_of"] == "2026-10-07T06:00:00Z"
    assert result["freshness_limit_hours"] == 24
    assert result["is_stale"] is False
    assert result["warnings"] == ["Players not listed are presumed available."]


async def test_team_with_no_absences_uses_last_sync_time(ctx):
    result = await availability(ctx, team_id=BRE)

    assert result["data"]["entries"] == []
    assert result["as_of"] == "2026-10-07T06:05:00Z"


async def test_player_filter(ctx):
    result = await availability(ctx, player_id=SAKA)

    assert [(e["player"]["id"], e["status"]) for e in result["data"]["entries"]] == [
        (SAKA, "doubtful")
    ]


async def test_never_synced_is_no_data(ctx, conn):
    await conn.execute("DELETE FROM job_runs")
    await conn.execute("DELETE FROM availability")

    result = await availability(ctx, team_id=BRE)
    assert result["error"]["code"] == "no_data"


async def test_unknown_fixture_is_not_found(ctx):
    result = await availability(ctx, fixture_id=99999)
    assert result["error"]["code"] == "not_found"


async def test_unknown_team_is_not_found(ctx):
    result = await availability(ctx, team_id=99999)
    assert result["error"]["code"] == "not_found"


async def test_unknown_player_is_not_found(ctx):
    result = await availability(ctx, player_id=99999)
    assert result["error"]["code"] == "not_found"


async def test_team_not_in_fixture_is_invalid(ctx):
    result = await availability(ctx, fixture_id=201, team_id=BRE)
    assert result["error"]["code"] == "invalid_input"
