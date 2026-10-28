"""Read-only access to the database the eval runs against (the hosted one, normally).

Two layers stop a write: every pooled session defaults to read-only transactions, and each
question runs inside one REPEATABLE READ, READ ONLY transaction, so the tools and the SQL
oracle also see the same snapshot while ingestion keeps writing.
"""

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg

URL_VARIABLE = "EVAL_DATABASE_URL"
ENV_FILE_KEY = "DATABASE_URL"


def database_url(env_file: Path | None, environ: Mapping[str, str] = os.environ) -> str:
    """EVAL_DATABASE_URL, or DATABASE_URL read from `env_file` (e.g. .env.production)."""
    if environ.get(URL_VARIABLE):
        return environ[URL_VARIABLE]
    if env_file is None:
        raise ValueError(f"Set {URL_VARIABLE} or pass --db-env-file (e.g. .env.production).")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition("=")
        if key == ENV_FILE_KEY and value:
            return value.strip().strip("\"'")
    raise ValueError(f"No {ENV_FILE_KEY} in {env_file}.")


async def _read_only_session(conn: asyncpg.Connection) -> None:
    await conn.execute("SET default_transaction_read_only = on")


async def read_only_pool(dsn: str, size: int) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=size, init=_read_only_session)


@asynccontextmanager
async def snapshot(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """One connection inside a read-only transaction with a fixed view of the data."""
    async with (
        pool.acquire() as conn,
        conn.transaction(isolation="repeatable_read", readonly=True),
    ):
        yield conn
