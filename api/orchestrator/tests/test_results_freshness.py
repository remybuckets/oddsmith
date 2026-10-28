"""Freshness of finished-match data (decision 10): as of the last results sync, stale only
when a result is missing hours after kick-off.

Eval regression (run 3): finished matches are loaded once and never re-fetched, so under the
oldest-fetched_at rule 20 of 50 answers called current stats "18 days old"."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.tests.seed import AVL, BRE, HAALAND, MCI, NEW, NOW
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio

RESULTS_SYNCED = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)

# Each touches fixture 109, whose rows were fetched on 4 Oct: stale under the old rule.
FINISHED_MATCH_CALLS = [
    ("get_player_stats", {"player_id": HAALAND}),
    ("get_team_stats", {"team_id": MCI}),
    ("get_league_table", {}),
    ("get_head_to_head", {"team_a_id": NEW, "team_b_id": MCI}),
]


async def _results_sync(conn, finished_at, status="success"):
    await conn.execute(
        "INSERT INTO job_runs (name, started_at, finished_at, status) VALUES ($1, $2, $3, $4)",
        "sync_results",
        finished_at - timedelta(minutes=1),
        finished_at,
        status,
    )


async def _fixture_without_result(conn, kicked_off_hours_ago, status="live"):
    await conn.execute(
        "INSERT INTO fixtures (id, provider_id, season, matchweek, home_id, away_id, kickoff_at,"
        " status) VALUES (999, 9999, '2026/27', 4, $1, $2, $3, $4)",
        AVL,
        BRE,
        NOW - timedelta(hours=kicked_off_hours_ago),
        status,
    )


@pytest.mark.parametrize(("tool", "args"), FINISHED_MATCH_CALLS)
async def test_finished_match_data_is_as_of_the_last_results_sync(conn, ctx, tool, args):
    await _results_sync(conn, RESULTS_SYNCED)
    await _results_sync(conn, NOW - timedelta(minutes=30), status="failed")

    result = await run_tool(ctx, tool, args)

    assert result["as_of"] == "2026-10-07T01:00:00Z"
    assert result["is_stale"] is False
    assert result["freshness_limit_hours"] == 3


@pytest.mark.parametrize(("tool", "args"), FINISHED_MATCH_CALLS)
async def test_a_result_missing_hours_after_kick_off_is_stale(conn, ctx, tool, args):
    await _results_sync(conn, RESULTS_SYNCED)
    await _fixture_without_result(conn, kicked_off_hours_ago=4)

    result = await run_tool(ctx, tool, args)

    assert result["is_stale"] is True


@pytest.mark.parametrize(
    ("hours_ago", "status"),
    [(2, "live"), (30, "postponed"), (30, "cancelled")],
)
async def test_a_match_still_playing_or_called_off_is_not_a_missing_result(
    conn, ctx, hours_ago, status
):
    await _results_sync(conn, RESULTS_SYNCED)
    await _fixture_without_result(conn, kicked_off_hours_ago=hours_ago, status=status)

    result = await run_tool(ctx, "get_team_stats", {"team_id": MCI})

    assert result["is_stale"] is False


async def test_without_a_results_sync_the_rows_own_fetch_times_count(ctx):
    # No sync_results run yet (a fresh database after the backfill): fall back to the
    # oldest fetched_at, so fixture 109's 4 Oct rows still read as stale.
    result = await run_tool(ctx, "get_team_stats", {"team_id": MCI})

    assert result["as_of"] == "2026-10-04T00:00:00Z"
    assert result["is_stale"] is True
    assert result["freshness_limit_hours"] == 48
