"""Run one ingestion job: `uv run python -m oddsmith_ingestion.cli <job> [options]`."""

import argparse
import asyncio
import logging

import asyncpg
import httpx

from oddsmith_ingestion.jobs.seed_reference import seed_reference
from oddsmith_ingestion.providers.api_football import ApiFootballClient
from oddsmith_ingestion.settings import Settings, load_settings

JOBS = ("seed_reference",)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="oddsmith-ingestion")
    parser.add_argument("job", choices=JOBS)
    parser.add_argument(
        "--no-full-names",
        dest="full_names",
        action="store_false",
        help="seed_reference: skip /players full-name lookups (~60 API-Football requests)",
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
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        async with httpx.AsyncClient() as http:
            client = api_football(http, settings)
            rows = await seed_reference(
                pool,
                client,
                season=settings.api_football_season,
                include_full_names=args.full_names,
            )
            logging.info("api-football quota remaining: %s", client.quota_remaining)
            return rows
    finally:
        await pool.close()


def main() -> None:  # pragma: no cover - thin wrapper
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(parse_args(), load_settings()))


if __name__ == "__main__":  # pragma: no cover
    main()
