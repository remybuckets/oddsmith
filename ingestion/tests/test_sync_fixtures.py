import copy
from datetime import UTC, datetime

import pytest
from conftest import load_fixture

from oddsmith_ingestion.jobs.sync_fixtures import sync_fixtures

SEASON = 2024
MUN_FUL = 1208021


class FakeFixtures:
    def __init__(self, response=None):
        self.response = response or load_fixture("api_football", "fixtures_season")["response"]

    async def fixtures(self, season):
        assert season == SEASON
        return self.response


async def test_upserts_every_fixture_of_the_season(db):
    # Act
    rows = await sync_fixtures(db, FakeFixtures(), season=SEASON)
    # Assert
    assert rows == 380
    f = await db.fetchrow(
        """SELECT f.*, h.name AS home, a.name AS away FROM fixtures f
           JOIN teams h ON h.id = f.home_id JOIN teams a ON a.id = f.away_id
           WHERE f.provider_id = $1""",
        MUN_FUL,
    )
    assert (f["home"], f["away"]) == ("Manchester United", "Fulham")
    assert f["season"] == "2024/25"
    assert f["matchweek"] == 1
    assert f["status"] == "finished"
    assert (f["home_score"], f["away_score"]) == (1, 0)
    assert f["kickoff_at"] == datetime(2024, 8, 16, 19, 0, tzinfo=UTC)
    run = await db.fetchrow("SELECT * FROM job_runs WHERE name = 'sync_fixtures'")
    assert (run["status"], run["rows"]) == ("success", 380)


async def test_creates_missing_teams_with_curated_aliases(db):
    await sync_fixtures(db, FakeFixtures(), season=SEASON)
    assert await db.fetchval("SELECT count(*) FROM teams") == 20
    assert (
        await db.fetchval(
            "SELECT t.name FROM entity_aliases a JOIN teams t ON t.id = a.entity_id "
            "WHERE a.entity_type = 'team' AND a.alias_search = 'spurs'"
        )
        == "Tottenham"
    )


async def test_keeps_existing_team_rows_untouched(db):
    await db.execute(
        "INSERT INTO teams (provider_id, name, short_name) VALUES (47, 'Tottenham', 'Custom')"
    )
    await sync_fixtures(db, FakeFixtures(), season=SEASON)
    assert await db.fetchval("SELECT short_name FROM teams WHERE provider_id = 47") == "Custom"


async def test_is_idempotent_and_applies_changes(db):
    await sync_fixtures(db, FakeFixtures(), season=SEASON)
    changed = copy.deepcopy(FakeFixtures().response)
    item = next(f for f in changed if f["fixture"]["id"] == MUN_FUL)
    item["fixture"]["status"]["short"] = "PST"
    item["fixture"]["date"] = "2024-09-01T14:00:00+00:00"
    item["goals"] = {"home": None, "away": None}

    await sync_fixtures(db, FakeFixtures(changed), season=SEASON)

    assert await db.fetchval("SELECT count(*) FROM fixtures") == 380
    f = await db.fetchrow("SELECT * FROM fixtures WHERE provider_id = $1", MUN_FUL)
    assert f["status"] == "postponed"
    assert f["home_score"] is None
    assert f["kickoff_at"] == datetime(2024, 9, 1, 14, 0, tzinfo=UTC)


async def test_unknown_status_fails_the_job_and_writes_nothing(db):
    broken = copy.deepcopy(FakeFixtures().response)
    broken[5]["fixture"]["status"]["short"] = "???"
    with pytest.raises(ValueError):
        await sync_fixtures(db, FakeFixtures(broken), season=SEASON)
    assert await db.fetchval("SELECT count(*) FROM fixtures") == 0
    assert await db.fetchval("SELECT status FROM job_runs") == "failed"
