"""backfill_season: one season's fixtures plus results and stats for every played match.

Run once per season (2026 and 2025 for the beta). Re-running only fetches matches still
missing stats. Cost on API-Football (Pro): 1 + ceil(played matches / 20) requests.
"""

from datetime import UTC, datetime
from typing import Protocol

import asyncpg

from oddsmith_ingestion.job_runs import run_job
from oddsmith_ingestion.jobs.sync_fixtures import FixtureSource, upsert_fixtures
from oddsmith_ingestion.jobs.sync_results import ResultSource, fetch_results

JOB_NAME = "backfill_season"


class SeasonSource(FixtureSource, ResultSource, Protocol): ...


async def backfill_season(
    pool: asyncpg.Pool, client: SeasonSource, *, season: int, now: datetime | None = None
) -> int:
    at = now or datetime.now(UTC)

    async def work() -> int:
        raw = await client.fixtures(season)
        async with pool.acquire() as conn, conn.transaction():
            fixtures = await upsert_fixtures(conn, raw, season)
        return fixtures + await fetch_results(pool, client, season, at, window=None)

    return await run_job(pool, JOB_NAME, work)
