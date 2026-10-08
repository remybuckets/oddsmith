"""Run ingestion jobs: `uv run python -m oddsmith_ingestion.cli <job> [options]`.

`tick` runs every job that is due (see schedule.py); point a 30-minute cron at it.
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg
import httpx

from oddsmith_ingestion.jobs.backfill_season import backfill_season
from oddsmith_ingestion.jobs.seed_reference import seed_reference
from oddsmith_ingestion.jobs.sync_availability import sync_availability
from oddsmith_ingestion.jobs.sync_fixtures import sync_fixtures
from oddsmith_ingestion.jobs.sync_odds import sync_btts, sync_odds
from oddsmith_ingestion.jobs.sync_results import sync_results
from oddsmith_ingestion.providers.api_football import ApiFootballClient
from oddsmith_ingestion.providers.odds_api import OddsApiClient
from oddsmith_ingestion.schedule import btts_horizon, due_jobs, load_state
from oddsmith_ingestion.settings import Settings, load_settings

logger = logging.getLogger(__name__)

# Postgres advisory lock key held for a whole tick, so a slow tick never overlaps the next.
TICK_LOCK_ID = 7_020_261_007


@dataclass(frozen=True)
class Context:
    pool: asyncpg.Pool
    api_football: ApiFootballClient
    odds_api: OddsApiClient
    season: int
    full_names: bool = True
    odds_cadence: str = "full"


RUNNERS: dict[str, Callable[[Context], Awaitable[int]]] = {
    "seed_reference": lambda c: seed_reference(
        c.pool, c.api_football, season=c.season, include_full_names=c.full_names
    ),
    "sync_fixtures": lambda c: sync_fixtures(c.pool, c.api_football, season=c.season),
    "sync_results": lambda c: sync_results(c.pool, c.api_football, season=c.season),
    "sync_availability": lambda c: sync_availability(c.pool, c.api_football, season=c.season),
    "sync_odds": lambda c: sync_odds(c.pool, c.odds_api),
    "sync_btts": lambda c: sync_btts(c.pool, c.odds_api, horizon=btts_horizon(c.odds_cadence)),
    "backfill_season": lambda c: backfill_season(c.pool, c.api_football, season=c.season),
}
JOBS = (*RUNNERS, "tick")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="oddsmith-ingestion")
    parser.add_argument("job", choices=JOBS)
    parser.add_argument(
        "--no-full-names",
        dest="full_names",
        action="store_false",
        help="seed_reference: skip /players full-name lookups (~60 API-Football requests)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="API-Football season year (default: API_FOOTBALL_SEASON), e.g. 2025 for 2025/26",
    )
    return parser.parse_args(argv)


async def tick(ctx: Context, now: datetime) -> list[str]:
    """Run every due job; a failure is already in job_runs and doesn't stop the others.
    Returns the names of jobs that failed."""
    async with ctx.pool.acquire() as lock_conn:
        if not await lock_conn.fetchval("SELECT pg_try_advisory_lock($1)", TICK_LOCK_ID):
            logger.warning("tick: previous tick still running, skipping")
            return []
        try:
            state = await load_state(ctx.pool, season=ctx.season, now=now)
            due = due_jobs(state, odds_cadence=ctx.odds_cadence)
            logger.info("tick: due %s", due or "nothing")
            failed = []
            for job in due:
                try:
                    await RUNNERS[job](ctx)
                except Exception:
                    logger.exception("tick: %s failed", job)
                    failed.append(job)
            return failed
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", TICK_LOCK_ID)


async def run(args: argparse.Namespace, settings: Settings) -> bool:
    """Run the requested job. Returns True on success."""
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=3)
    try:
        async with httpx.AsyncClient() as http:
            ctx = Context(
                pool=pool,
                api_football=ApiFootballClient(
                    http,
                    api_key=settings.api_football_key,
                    quota_reserve=settings.api_football_quota_reserve,
                    min_interval=settings.api_football_min_interval,
                ),
                odds_api=OddsApiClient(
                    http,
                    api_key=settings.odds_api_key,
                    quota_reserve=settings.odds_api_quota_reserve,
                ),
                season=args.season or settings.api_football_season,
                full_names=args.full_names,
                odds_cadence=settings.odds_cadence,
            )
            if args.job == "tick":
                ok = not await tick(ctx, datetime.now(UTC))
            else:
                await RUNNERS[args.job](ctx)
                ok = True
            logger.info(
                "quota remaining: api-football %s, the-odds-api %s",
                ctx.api_football.quota_remaining,
                ctx.odds_api.quota_remaining,
            )
            return ok
    finally:
        await pool.close()


def main() -> None:  # pragma: no cover - thin wrapper
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(0 if asyncio.run(run(parse_args(), load_settings())) else 1)


if __name__ == "__main__":  # pragma: no cover
    main()
