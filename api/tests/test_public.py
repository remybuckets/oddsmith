"""Routes that need no sign-in: /health and /fixtures/next."""

from datetime import timedelta

from tests.conftest import NOW


async def _job(pool, name, status, finished_at):
    await pool.execute(
        "INSERT INTO job_runs (name, started_at, finished_at, status) VALUES ($1, $2, $3, $4)",
        name,
        finished_at - timedelta(minutes=1),
        finished_at,
        status,
    )


async def test_health_with_no_runs_is_degraded(client):
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "degraded"
    assert {job["name"] for job in data["jobs"]} >= {"sync_fixtures", "sync_odds"}
    assert all(job["last_success_at"] is None and job["is_stale"] for job in data["jobs"])


async def test_health_reports_last_success_and_staleness(client, pool):
    await _job(pool, "sync_odds", "success", NOW - timedelta(hours=7))
    await _job(pool, "sync_odds", "failed", NOW - timedelta(hours=1))
    await _job(pool, "sync_availability", "success", NOW - timedelta(hours=2))

    jobs = {j["name"]: j for j in (await client.get("/health")).json()["data"]["jobs"]}

    assert jobs["sync_odds"]["last_success_at"] == "2026-10-10T04:00:00Z"
    assert jobs["sync_odds"]["is_stale"] is True
    assert jobs["sync_availability"]["is_stale"] is False


async def test_health_ok_when_every_job_is_fresh(client, pool):
    for name in (
        "seed_reference",
        "backfill_season",
        "sync_fixtures",
        "sync_results",
        "sync_availability",
        "sync_odds",
    ):
        await _job(pool, name, "success", NOW - timedelta(minutes=10))

    assert (await client.get("/health")).json()["data"]["status"] == "ok"


async def _team(pool, provider_id, name, short_name) -> int:
    return await pool.fetchval(
        "INSERT INTO teams (provider_id, name, short_name) VALUES ($1, $2, $3) RETURNING id",
        provider_id,
        name,
        short_name,
    )


async def _fixture(pool, provider_id, home, away, kickoff, matchweek, status="scheduled"):
    return await pool.fetchval(
        """INSERT INTO fixtures (provider_id, season, matchweek, home_id, away_id, kickoff_at,
                                 status)
           VALUES ($1, '2026/27', $2, $3, $4, $5, $6) RETURNING id""",
        provider_id,
        matchweek,
        home,
        away,
        kickoff,
        status,
    )


async def test_fixtures_next_returns_next_matchweek(client, pool):
    villa = await _team(pool, 66, "Aston Villa", "Villa")
    spurs = await _team(pool, 47, "Tottenham Hotspur", "Spurs")
    arsenal = await _team(pool, 42, "Arsenal", "Arsenal")
    await _fixture(pool, 1, arsenal, villa, NOW - timedelta(days=7), 5, "finished")
    first = await _fixture(pool, 2, villa, spurs, NOW + timedelta(hours=3), 6)
    await _fixture(pool, 3, spurs, arsenal, NOW + timedelta(days=1), 6)
    await _fixture(pool, 4, arsenal, spurs, NOW + timedelta(days=8), 7)

    response = await client.get("/fixtures/next")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["matchweek"] == 6
    assert len(data["fixtures"]) == 2
    assert data["fixtures"][0] == {
        "fixture_id": first,
        "matchweek": 6,
        "kickoff_at": "2026-10-10T14:00:00Z",
        "status": "scheduled",
        "home": {"id": villa, "name": "Aston Villa", "short_name": "Villa"},
        "away": {"id": spurs, "name": "Tottenham Hotspur", "short_name": "Spurs"},
        "home_score": None,
        "away_score": None,
    }
    questions = data["suggested_questions"]
    assert 1 <= len(questions) <= 6
    assert "Who's injured for Villa vs Spurs?" in questions
    banned = ("lock", "banker", "guaranteed", "sure thing")
    assert not any(word in q.lower() for q in questions for word in banned)


async def test_fixtures_next_without_upcoming_fixtures_is_not_found(client):
    response = await client.get("/fixtures/next")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
