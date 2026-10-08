from datetime import UTC, datetime, timedelta

import pytest

from oddsmith_ingestion.matchweek_check import check_matchweek, current_matchweek
from oddsmith_ingestion.repository import ensure_teams

SEASON = 2026
KICKOFF = datetime(2026, 10, 10, 14, 0, tzinfo=UTC)
ARS, LEE, CHE, EVE = (
    {"id": 42, "name": "Arsenal"},
    {"id": 63, "name": "Leeds"},
    {"id": 49, "name": "Chelsea"},
    {"id": 45, "name": "Everton"},
)


@pytest.fixture
async def mw6(db):
    """Two MW6 fixtures (Arsenal v Leeds, Chelsea v Everton) and one MW5 fixture."""
    async with db.acquire() as conn:
        ids = await ensure_teams(conn, [ARS, LEE, CHE, EVE])
    for pid, home, away, mw, kickoff in [
        (1, ARS, LEE, 6, KICKOFF),
        (2, CHE, EVE, 6, KICKOFF + timedelta(days=1)),
        (3, LEE, CHE, 5, KICKOFF - timedelta(days=7)),
    ]:
        await db.execute(
            """INSERT INTO fixtures (provider_id, season, matchweek, home_id, away_id,
                                     kickoff_at, status)
               VALUES ($1, '2026/27', $2, $3, $4, $5, 'scheduled')""",
            pid,
            mw,
            ids[home["id"]],
            ids[away["id"]],
            kickoff,
        )
    return db


async def add_odds(db, provider_id, captured_at, selections=("home", "draw", "away")):
    fixture_id = await db.fetchval("SELECT id FROM fixtures WHERE provider_id = $1", provider_id)
    for sel in selections:
        await db.execute(
            """INSERT INTO odds_snapshots (fixture_id, market, selection, bookmaker, price,
                                           captured_at)
               VALUES ($1, 'h2h', $2, 'skybet', 2.5, $3)""",
            fixture_id,
            sel,
            captured_at,
        )


async def add_job(db, name, status, started_at, error=None):
    await db.execute(
        "INSERT INTO job_runs (name, status, started_at, finished_at, error) "
        "VALUES ($1, $2, $3, $3, $4)",
        name,
        status,
        started_at,
        error,
    )


async def finish_with_stats(db, provider_id, home_goals=2, away_goals=1, players=22):
    f = await db.fetchrow(
        "UPDATE fixtures SET status = 'finished', home_score = $2, away_score = $3 "
        "WHERE provider_id = $1 RETURNING id, home_id, away_id",
        provider_id,
        home_goals,
        away_goals,
    )
    for team, venue, gf, ga in [
        (f["home_id"], "home", home_goals, away_goals),
        (f["away_id"], "away", away_goals, home_goals),
    ]:
        await db.execute(
            """INSERT INTO team_match_stats (fixture_id, team_id, venue, goals_for,
                                             goals_against, xg_for, xg_against)
               VALUES ($1, $2, $3, $4, $5, 1.1, 0.9)""",
            f["id"],
            team,
            venue,
            gf,
            ga,
        )
    for n in range(players):
        pid = await db.fetchval(
            "INSERT INTO players (provider_id, name) VALUES ($1, $2) RETURNING id",
            provider_id * 1000 + n,
            f"P{n}",
        )
        await db.execute(
            "INSERT INTO player_match_stats (fixture_id, player_id, team_id, minutes) "
            "VALUES ($1, $2, $3, 90)",
            f["id"],
            pid,
            f["home_id"] if n % 2 else f["away_id"],
        )


def checks(report):
    return {(p.fixture, p.check) for p in report.problems}


async def test_current_matchweek_is_the_one_in_play_or_next(mw6):
    async with mw6.acquire() as conn:
        assert await current_matchweek(conn, SEASON, KICKOFF - timedelta(days=2)) == 6
        assert await current_matchweek(conn, SEASON, KICKOFF + timedelta(hours=5)) == 6


async def test_healthy_pre_matchweek_state_has_no_problems(mw6):
    now = KICKOFF - timedelta(hours=3)
    await add_odds(mw6, 1, now - timedelta(hours=1))
    await add_odds(mw6, 2, now - timedelta(hours=1))
    await add_job(mw6, "sync_availability", "success", now - timedelta(hours=2))
    report = await check_matchweek(mw6, season=SEASON, now=now)
    assert report.matchweek == 6
    assert len(report.fixtures) == 2
    assert report.problems == []


async def test_flags_missing_and_stale_odds_before_kickoff(mw6):
    now = KICKOFF - timedelta(hours=3)
    await add_odds(mw6, 1, now - timedelta(hours=7))
    await add_job(mw6, "sync_availability", "success", now)
    report = await check_matchweek(mw6, season=SEASON, now=now)
    assert checks(report) == {
        ("Arsenal v Leeds", "odds_stale"),
        ("Chelsea v Everton", "odds_missing"),
    }


async def test_flags_incomplete_h2h(mw6):
    now = KICKOFF - timedelta(hours=1)
    await add_odds(mw6, 1, now, selections=("home", "away"))
    await add_odds(mw6, 2, now)
    await add_job(mw6, "sync_availability", "success", now)
    assert ("Arsenal v Leeds", "odds_incomplete") in checks(
        await check_matchweek(mw6, season=SEASON, now=now)
    )


async def test_flags_stale_availability(mw6):
    now = KICKOFF - timedelta(hours=3)
    await add_odds(mw6, 1, now)
    await add_odds(mw6, 2, now)
    await add_job(mw6, "sync_availability", "success", now - timedelta(hours=30))
    assert (None, "availability_stale") in checks(
        await check_matchweek(mw6, season=SEASON, now=now)
    )


async def test_flags_results_overdue_three_hours_after_kickoff(mw6):
    now = KICKOFF + timedelta(hours=3, minutes=5)
    await add_odds(mw6, 2, now)
    await add_job(mw6, "sync_availability", "success", now)
    assert ("Arsenal v Leeds", "result_overdue") in checks(
        await check_matchweek(mw6, season=SEASON, now=now)
    )


async def test_finished_fixture_with_full_stats_passes(mw6):
    now = KICKOFF + timedelta(hours=4)
    await finish_with_stats(mw6, 1)
    await add_odds(mw6, 2, now)
    await add_job(mw6, "sync_availability", "success", now)
    report = await check_matchweek(mw6, season=SEASON, now=now)
    assert report.problems == []


async def test_flags_thin_player_stats_and_score_mismatch(mw6):
    now = KICKOFF + timedelta(hours=4)
    await finish_with_stats(mw6, 1, players=10)
    await mw6.execute("UPDATE fixtures SET home_score = 5 WHERE provider_id = 1")
    await add_odds(mw6, 2, now)
    await add_job(mw6, "sync_availability", "success", now)
    found = checks(await check_matchweek(mw6, season=SEASON, now=now))
    assert ("Arsenal v Leeds", "player_stats_thin") in found
    assert ("Arsenal v Leeds", "score_mismatch") in found


async def test_flags_recent_failed_job_runs(mw6):
    now = KICKOFF - timedelta(hours=3)
    await add_odds(mw6, 1, now)
    await add_odds(mw6, 2, now)
    await add_job(mw6, "sync_availability", "success", now)
    await add_job(mw6, "sync_odds", "failed", now - timedelta(hours=1), "QuotaExhausted: 0 left")
    report = await check_matchweek(mw6, season=SEASON, now=now)
    assert (None, "job_failed") in checks(report)
    assert any("QuotaExhausted" in p.detail for p in report.problems)
