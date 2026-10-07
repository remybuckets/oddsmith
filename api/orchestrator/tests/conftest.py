import os
from collections.abc import AsyncIterator

import asyncpg
import pytest_asyncio

from orchestrator.tests.seed import NOW, seed
from orchestrator.tools.context import ToolContext

# Built by `db/test-db.sh orchestrator`; override when the local stack runs elsewhere.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql://postgres:postgres@127.0.0.1:54322/oddsmith_test_orchestrator"
)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    """A seeded connection inside a transaction that is rolled back after each test."""
    url = os.environ.get("ORCHESTRATOR_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    connection = await asyncpg.connect(url)
    tx = connection.transaction()
    await tx.start()
    try:
        await seed(connection)
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def ctx(conn: asyncpg.Connection) -> ToolContext:
    return ToolContext(conn=conn, now=NOW)
