"""Shared fixtures. DB tests use the lane database built by `db/test-db.sh ingestion`."""

import json
import os
from pathlib import Path
from typing import Any

import asyncpg
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TEST_DATABASE_URL = os.environ.get(
    "INGESTION_TEST_DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:54322/oddsmith_test_ingestion",
)
# bookmakers is seeded by the migration, so it is never truncated.
DATA_TABLES = (
    "job_runs, odds_snapshots, availability, player_match_stats, team_match_stats, "
    "fixtures, entity_aliases, players, teams"
)


def load_fixture(provider: str, name: str) -> Any:
    return json.loads((FIXTURES / provider / f"{name}.json").read_text())


@pytest.fixture(scope="session")
async def pool():
    try:
        db_pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.fail(f"test database unavailable ({exc}); run db/test-db.sh ingestion")
    yield db_pool
    await db_pool.close()


@pytest.fixture
async def db(pool):
    """A clean database for each test."""
    await pool.execute(f"TRUNCATE {DATA_TABLES} RESTART IDENTITY CASCADE")
    return pool
