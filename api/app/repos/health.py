"""job_runs: last successful run per ingestion job, and whether it's overdue.

Thresholds follow ingestion's schedule (ingestion/src/oddsmith_ingestion/schedule.py, lean odds
cadence per DECISIONS 8) plus room for one missed run, so a stale flag means something is broken.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import asyncpg

# None: runs only when there's something to do, so stale only if it has never succeeded.
JOB_MAX_AGE: dict[str, timedelta | None] = {
    "seed_reference": timedelta(days=8),  # weekly
    "backfill_season": None,  # once
    "sync_fixtures": timedelta(hours=30),  # daily from 06:00 UK
    "sync_results": None,  # judged by overdue results instead, see below
    "sync_availability": timedelta(hours=13),  # every 6h, hourly near kick-off
    "sync_odds": timedelta(hours=26),  # lean: daily off matchdays, 2-hourly on them
    "sync_btts": None,  # matchday mornings only
}
RESULTS_JOB = "sync_results"
RESULTS_GRACE = timedelta(hours=4)  # kick-off to final whistle plus ingestion lag
RESULTS_LOOKBACK = timedelta(days=7)


@dataclass(frozen=True)
class JobHealth:
    name: str
    last_success_at: datetime | None
    is_stale: bool


def _is_stale(last_success_at: datetime | None, max_age: timedelta | None, now: datetime) -> bool:
    if last_success_at is None:
        return True
    return max_age is not None and now - last_success_at > max_age


async def _results_overdue(pool: asyncpg.Pool, now: datetime) -> bool:
    """A recent match that should be over is still not marked finished."""
    return bool(
        await pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM fixtures
                WHERE kickoff_at BETWEEN $1 AND $2 AND status IN ('scheduled', 'live')
            )
            """,
            now - RESULTS_LOOKBACK,
            now - RESULTS_GRACE,
        )
    )


async def job_health(pool: asyncpg.Pool, now: datetime) -> list[JobHealth]:
    rows = await pool.fetch(
        """
        SELECT name, max(finished_at) AS last_success_at
        FROM job_runs
        WHERE status = 'success' AND name = ANY($1::text[])
        GROUP BY name
        """,
        list(JOB_MAX_AGE),
    )
    last_success = {row["name"]: row["last_success_at"] for row in rows}
    results_overdue = await _results_overdue(pool, now)

    def stale(name: str, max_age: timedelta | None) -> bool:
        overdue = results_overdue if name == RESULTS_JOB else False
        return _is_stale(last_success.get(name), max_age, now) or overdue

    return [
        JobHealth(name, last_success.get(name), stale(name, max_age))
        for name, max_age in JOB_MAX_AGE.items()
    ]
