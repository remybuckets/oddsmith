"""job_runs: last successful run per ingestion job, and whether it's overdue."""

from dataclasses import dataclass
from datetime import datetime, timedelta

import asyncpg

# How long after its last success each job counts as stale. Freshness limits from SPEC.md
# (odds 6h, availability 24h, stats 48h); schedule-based for the rest. None: never stale once run.
JOB_MAX_AGE: dict[str, timedelta | None] = {
    "seed_reference": timedelta(days=8),
    "backfill_season": None,
    "sync_fixtures": timedelta(hours=26),
    "sync_results": timedelta(hours=48),
    "sync_availability": timedelta(hours=24),
    "sync_odds": timedelta(hours=6),
}


@dataclass(frozen=True)
class JobHealth:
    name: str
    last_success_at: datetime | None
    is_stale: bool


def _is_stale(last_success_at: datetime | None, max_age: timedelta | None, now: datetime) -> bool:
    if last_success_at is None:
        return True
    return max_age is not None and now - last_success_at > max_age


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
    return [
        JobHealth(name, last_success.get(name), _is_stale(last_success.get(name), max_age, now))
        for name, max_age in JOB_MAX_AGE.items()
    ]
