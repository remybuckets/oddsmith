import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from conftest import load_fixture
from test_sync_fixtures import FakeFixtures

from oddsmith_ingestion.jobs.sync_fixtures import sync_fixtures
from oddsmith_ingestion.jobs.sync_results import sync_results

SEASON = 2024
MUN_FUL = 1208021
MUN, FUL = 33, 36
AFTER_MW1 = datetime(2024, 8, 20, tzinfo=UTC)  # MW1: Fri 16 Aug 19:00 to Mon 19 Aug 19:00


def detailed(item):
    """A /fixtures?ids= item: the fixture plus statistics and players. Built from the real
    recorded /fixtures/statistics and /fixtures/players responses for MUN v FUL; other
    fixtures come back without stats (as the provider does before they are published)."""
    has_stats = item["fixture"]["id"] == MUN_FUL
    return {
        **item,
        "events": [],
        "lineups": [],
        "statistics": load_fixture("api_football", "fixture_statistics")["response"]
        if has_stats
        else [],
        "players": load_fixture("api_football", "fixture_players")["response"] if has_stats else [],
    }


class FakeDetails:
    def __init__(self, season_response=None):
        season = season_response or load_fixture("api_football", "fixtures_season")["response"]
        self.by_id = {f["fixture"]["id"]: f for f in season}
        self.requested: list[list[int]] = []

    async def fixtures_by_ids(self, ids):
        assert len(ids) <= 20
        self.requested.append(list(ids))
        return [detailed(self.by_id[i]) for i in ids]


async def synced(db):
    await sync_fixtures(db, FakeFixtures(), season=SEASON)
    return db


async def team_stats(db, team_pid):
    return await db.fetchrow(
        """SELECT s.* FROM team_match_stats s JOIN teams t ON t.id = s.team_id
           JOIN fixtures f ON f.id = s.fixture_id
           WHERE f.provider_id = $1 AND t.provider_id = $2""",
        MUN_FUL,
        team_pid,
    )


async def test_writes_team_stats_with_xg_both_ways(db):
    await synced(db)
    await sync_results(db, FakeDetails(), season=SEASON, now=AFTER_MW1)

    mun, ful = await team_stats(db, MUN), await team_stats(db, FUL)
    assert (mun["venue"], mun["goals_for"], mun["goals_against"]) == ("home", 1, 0)
    assert (ful["venue"], ful["goals_for"], ful["goals_against"]) == ("away", 0, 1)
    assert mun["xg_for"] == Decimal("2.43")
    assert mun["xg_against"] == ful["xg_for"]
    assert mun["corners"] == 7
    assert mun["yellow_cards"] == 2
    assert mun["red_cards"] == 0  # provider sends null


async def test_writes_player_stats_for_players_who_played(db):
    await synced(db)
    await sync_results(db, FakeDetails(), season=SEASON, now=AFTER_MW1)

    rows = await db.fetch(
        """SELECT p.name, s.* FROM player_match_stats s JOIN players p ON p.id = s.player_id
           JOIN fixtures f ON f.id = s.fixture_id WHERE f.provider_id = $1""",
        MUN_FUL,
    )
    assert len(rows) == 40 - 8  # unused substitutes (no minutes) are skipped
    onana = next(r for r in rows if r["name"] == "André Onana")
    assert onana["minutes"] == 90
    assert onana["shots"] == 0  # null -> 0
    assert onana["xg"] is None  # API-Football has no player xG
    assert sum(r["goals"] for r in rows) == 1
    team_of = {r["team_id"] for r in rows}
    assert len(team_of) == 2


async def test_creates_unknown_players_without_a_current_club(db):
    await synced(db)
    await sync_results(db, FakeDetails(), season=SEASON, now=AFTER_MW1)
    onana = await db.fetchrow("SELECT * FROM players WHERE name = 'André Onana'")
    assert onana["team_id"] is None
    assert onana["position"] == "GK"
    assert (
        await db.fetchval(
            "SELECT count(*) FROM entity_aliases WHERE entity_type = 'player' "
            "AND entity_id = $1 AND alias_search = 'andre onana'",
            onana["id"],
        )
        == 1
    )


async def test_only_fetches_recent_kicked_off_fixtures_in_batches_of_20(db):
    await synced(db)
    client = FakeDetails()
    await sync_results(db, client, season=SEASON, now=AFTER_MW1)
    # MW1 (10 fixtures) is within the window and >2h past kick-off; nothing else is.
    assert sum(len(batch) for batch in client.requested) == 10


async def test_skips_fixtures_that_already_have_stats(db):
    await synced(db)
    await sync_results(db, FakeDetails(), season=SEASON, now=AFTER_MW1)
    client = FakeDetails()
    await sync_results(db, client, season=SEASON, now=AFTER_MW1)
    requested = {i for batch in client.requested for i in batch}
    assert MUN_FUL not in requested
    assert len(requested) == 9  # the other MW1 fixtures still have no stats


async def test_waits_two_hours_after_kickoff(db):
    await synced(db)
    client = FakeDetails()
    kickoff = datetime(2024, 8, 16, 19, 0, tzinfo=UTC)
    await sync_results(db, client, season=SEASON, now=kickoff + timedelta(hours=1, minutes=59))
    assert client.requested == []


async def test_updates_score_and_status_of_a_fixture_that_just_finished(db):
    await synced(db)
    await db.execute(
        "UPDATE fixtures SET status = 'live', home_score = 0, away_score = 0 "
        "WHERE provider_id = $1",
        MUN_FUL,
    )
    await sync_results(db, FakeDetails(), season=SEASON, now=AFTER_MW1)
    f = await db.fetchrow("SELECT * FROM fixtures WHERE provider_id = $1", MUN_FUL)
    assert (f["status"], f["home_score"], f["away_score"]) == ("finished", 1, 0)


async def test_unfinished_fixture_gets_status_but_no_stats(db):
    season = copy.deepcopy(load_fixture("api_football", "fixtures_season")["response"])
    item = next(f for f in season if f["fixture"]["id"] == MUN_FUL)
    item["fixture"]["status"]["short"] = "SUSP"
    await synced(db)
    await sync_results(db, FakeDetails(season), season=SEASON, now=AFTER_MW1)
    assert (
        await db.fetchval("SELECT status FROM fixtures WHERE provider_id = $1", MUN_FUL) == "live"
    )
    assert await db.fetchval("SELECT count(*) FROM team_match_stats") == 0


async def test_no_window_means_whole_season(db):
    await synced(db)
    client = FakeDetails()
    rows = await sync_results(
        db, client, season=SEASON, now=datetime(2025, 7, 1, tzinfo=UTC), window=None
    )
    assert sum(len(b) for b in client.requested) == 380
    assert max(len(b) for b in client.requested) == 20
    assert rows == 2 + 32  # only MUN v FUL has stats in the recordings
    run = await db.fetchrow("SELECT * FROM job_runs WHERE name = 'sync_results'")
    assert (run["status"], run["rows"]) == ("success", rows)
