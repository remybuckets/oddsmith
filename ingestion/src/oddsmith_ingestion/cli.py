"""Run one ingestion job: `uv run python -m oddsmith_ingestion.cli <job> [options]`."""

import argparse
import asyncio
import logging

import asyncpg
import httpx

from oddsmith_ingestion.jobs.backfill_season import backfill_season
from oddsmith_ingestion.jobs.seed_reference import seed_reference
from oddsmith_ingestion.jobs.sync_fixtures import sync_fixtures
from oddsmith_ingestion.jobs.sync_results import sync_results
from oddsmith_ingestion.providers.api_football import ApiFootballClient
from oddsmith_ingestion.settings import Settings, load_settings

JOBS = ("seed_reference", "sync_fixtures", "sync_results", "backfill_season")


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


def api_football(http: httpx.AsyncClient, settings: Settings) -> ApiFootballClient:
    return ApiFootballClient(
        http,
        api_key=settings.api_football_key,
        quota_reserve=settings.api_football_quota_reserve,
        min_interval=settings.api_football_min_interval,
    )


async def run(args: argparse.Namespace, settings: Settings) -> int:
    season = args.season or settings.api_football_season
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        async with httpx.AsyncClient() as http:
            client = api_football(http, settings)
            rows = await dispatch(args, pool, client, season)
            logging.info("api-football quota remaining: %s", client.quota_remaining)
            return rows
    finally:
        await pool.close()


async def dispatch(
    args: argparse.Namespace, pool: asyncpg.Pool, client: ApiFootballClient, season: int
) -> int:
    if args.job == "seed_reference":
        return await seed_reference(pool, client, season=season, include_full_names=args.full_names)
    if args.job == "sync_fixtures":
        return await sync_fixtures(pool, client, season=season)
    if args.job == "sync_results":
        return await sync_results(pool, client, season=season)
    return await backfill_season(pool, client, season=season)


def main() -> None:  # pragma: no cover - thin wrapper
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(parse_args(), load_settings()))


if __name__ == "__main__":  # pragma: no cover
    main()
