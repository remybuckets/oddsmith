import copy
from datetime import UTC, datetime

import pytest
from conftest import load_fixture

from oddsmith_ingestion.jobs.sync_availability import build_availability, sync_availability
from oddsmith_ingestion.repository import ensure_teams

SEASON = 2026
ARS_LEE = 1557417  # recorded: Arsenal v Leeds, 2026-10-10 11:30 UTC
NOW = datetime(2026, 10, 7, 22, 0, tzinfo=UTC)


def injuries():
    return load_fixture("api_football", "injuries_upcoming")["response"]


class FakeInjuries:
    def __init__(self, response=None):
        self.response = response if response is not None else injuries()
        self.requested: list[int] = []

    async def injuries(self, season, **filters):
        assert season == SEASON
        self.requested.append(filters["fixture"])
        return self.response if filters["fixture"] == ARS_LEE else []


async def add_fixture(db, provider_id, home, away, kickoff, status="scheduled"):
    async with db.acquire() as conn:
        ids = await ensure_teams(conn, [home, away])
    await db.execute(
        """INSERT INTO fixtures (provider_id, season, home_id, away_id, kickoff_at, status)
           VALUES ($1, '2026/27', $2, $3, $4, $5)""",
        provider_id,
        ids[home["id"]],
        ids[away["id"]],
        kickoff,
        status,
    )


ARSENAL, LEEDS, CHELSEA = (
    {"id": 42, "name": "Arsenal"},
    {"id": 63, "name": "Leeds"},
    {"id": 49, "name": "Chelsea"},
)


@pytest.fixture
async def with_fixture(db):
    await add_fixture(db, ARS_LEE, ARSENAL, LEEDS, datetime(2026, 10, 10, 11, 30, tzinfo=UTC))
    return db


async def rows(db):
    return {
        r["name"]: r
        for r in await db.fetch(
            """SELECT p.name, t.provider_id AS team, a.* FROM availability a
               JOIN players p ON p.id = a.player_id JOIN teams t ON t.id = a.team_id"""
        )
    }


def test_build_availability_dedupes_and_maps_status():
    built = build_availability(injuries())
    assert len(built) == 9  # provider lists each player twice
    saliba = next(r for r in built if r.name == "W. Saliba")
    assert (saliba.status, saliba.reason, saliba.team_provider_id) == ("injured", "Back Injury", 42)
    assert {r.status for r in built} == {"injured", "doubtful"}


def test_build_availability_prefers_missing_over_questionable_for_same_player():
    raw = copy.deepcopy(injuries()[:1])
    doubtful = copy.deepcopy(raw[0])
    doubtful["player"]["type"] = "Questionable"
    assert [r.status for r in build_availability([doubtful, *raw])] == ["injured"]


async def test_writes_current_absences(with_fixture):
    db = with_fixture
    count = await sync_availability(db, FakeInjuries(), season=SEASON, now=NOW)
    current = await rows(db)
    assert count == 9
    assert len(current) == 9
    assert current["W. Saliba"]["status"] == "injured"
    assert current["W. Saliba"]["team"] == 42
    assert current["W. Saliba"]["source"] == "api-football"
    assert current["W. Saliba"]["expected_return"] is None
    run = await db.fetchrow("SELECT * FROM job_runs WHERE name = 'sync_availability'")
    assert (run["status"], run["rows"]) == ("success", 9)


async def test_player_fit_again_is_removed_and_unchanged_rows_keep_updated_at(with_fixture):
    db = with_fixture
    await sync_availability(db, FakeInjuries(), season=SEASON, now=NOW)
    before = await rows(db)
    later = [i for i in injuries() if i["player"]["name"] != "W. Saliba"]
    changed = next(i for i in later if i["player"]["name"] == "E. Konsa")
    for item in later:
        if item["player"]["id"] == changed["player"]["id"]:
            item["player"]["type"] = "Questionable"

    await sync_availability(db, FakeInjuries(later), season=SEASON, now=NOW)

    after = await rows(db)
    assert "W. Saliba" not in after
    assert after["E. Konsa"]["status"] == "doubtful"
    assert after["E. Konsa"]["updated_at"] > before["E. Konsa"]["updated_at"]
    unchanged = next(n for n in after if n != "E. Konsa")
    assert after[unchanged]["updated_at"] == before[unchanged]["updated_at"]


async def test_only_each_teams_next_scheduled_fixture_is_fetched(with_fixture):
    db = with_fixture
    await add_fixture(db, 2, ARSENAL, CHELSEA, datetime(2026, 10, 17, 14, 0, tzinfo=UTC))
    await add_fixture(db, 3, CHELSEA, LEEDS, datetime(2026, 10, 3, 14, 0, tzinfo=UTC), "finished")
    client = FakeInjuries()
    await sync_availability(db, client, season=SEASON, now=NOW)
    # Arsenal and Leeds -> ARS_LEE; Chelsea's next scheduled fixture is fixture 2.
    assert sorted(client.requested) == sorted([ARS_LEE, 2])


async def test_teams_not_covered_by_this_run_keep_their_rows(with_fixture):
    db = with_fixture
    async with db.acquire() as conn:
        chelsea = (await ensure_teams(conn, [CHELSEA]))[49]
    player = await db.fetchval(
        "INSERT INTO players (provider_id, name) VALUES (777, 'C. Blue') RETURNING id"
    )
    await db.execute(
        """INSERT INTO availability (team_id, player_id, status, source, updated_at)
           VALUES ($1, $2, 'injured', 'api-football', now())""",
        chelsea,
        player,
    )
    await sync_availability(db, FakeInjuries(), season=SEASON, now=NOW)
    assert "C. Blue" in await rows(db)


async def test_empty_reply_keeps_each_clubs_existing_rows(with_fixture):
    # API-Football publishes a fixture's list shortly before kick-off; empty means "not yet".
    db = with_fixture
    await sync_availability(db, FakeInjuries(), season=SEASON, now=NOW)
    before = await rows(db)

    await sync_availability(db, FakeInjuries([]), season=SEASON, now=NOW)

    assert await rows(db) == before


async def test_club_with_entries_is_replaced_while_club_without_entries_is_kept(with_fixture):
    db = with_fixture
    await sync_availability(db, FakeInjuries(), season=SEASON, now=NOW)
    before = await rows(db)
    arsenal_only = [
        i for i in injuries() if i["team"]["id"] == 42 and i["player"]["name"] != "W. Saliba"
    ]

    await sync_availability(db, FakeInjuries(arsenal_only), season=SEASON, now=NOW)

    after = await rows(db)
    assert "W. Saliba" not in after
    assert {n for n, r in after.items() if r["team"] == 42} == {
        n for n, r in before.items() if r["team"] == 42 and n != "W. Saliba"
    }
    leeds = {n: r for n, r in before.items() if r["team"] == 63}
    assert leeds and {n: after[n] for n in leeds} == leeds


async def test_empty_reply_still_records_a_successful_run(with_fixture):
    db = with_fixture
    count = await sync_availability(db, FakeInjuries([]), season=SEASON, now=NOW)
    run = await db.fetchrow("SELECT * FROM job_runs WHERE name = 'sync_availability'")
    assert count == 0
    assert (run["status"], run["rows"]) == ("success", 0)


async def test_rows_for_teams_not_covered_by_the_fixture_are_ignored(db):
    # Leeds' next fixture is earlier (fixture 5), so ARS_LEE only covers Arsenal.
    await add_fixture(db, ARS_LEE, ARSENAL, LEEDS, datetime(2026, 10, 10, 11, 30, tzinfo=UTC))
    await add_fixture(db, 5, CHELSEA, LEEDS, datetime(2026, 10, 9, 19, 0, tzinfo=UTC))

    await sync_availability(db, FakeInjuries(), season=SEASON, now=NOW)

    assert {r["team"] for r in (await rows(db)).values()} == {42}
