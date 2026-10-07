from datetime import UTC, datetime

from test_sync_fixtures import FakeFixtures
from test_sync_results import FakeDetails

from oddsmith_ingestion.jobs.backfill_season import backfill_season


class FakeClient(FakeFixtures, FakeDetails):
    def __init__(self):
        FakeFixtures.__init__(self)
        FakeDetails.__init__(self)


async def test_backfills_fixtures_and_all_results_as_one_job(db):
    client = FakeClient()

    rows = await backfill_season(db, client, season=2024, now=datetime(2025, 7, 1, tzinfo=UTC))

    assert await db.fetchval("SELECT count(*) FROM fixtures") == 380
    assert sum(len(b) for b in client.requested) == 380
    assert rows == 380 + 2 + 32
    runs = await db.fetch("SELECT name, status, rows FROM job_runs")
    assert [tuple(r) for r in runs] == [("backfill_season", "success", rows)]


async def test_rerun_only_fetches_fixtures_still_missing_stats(db):
    now = datetime(2025, 7, 1, tzinfo=UTC)
    await backfill_season(db, FakeClient(), season=2024, now=now)
    client = FakeClient()
    await backfill_season(db, client, season=2024, now=now)
    assert sum(len(b) for b in client.requested) == 379
