"""Postgres pool. Connect directly or through Supabase's session pooler, never the transaction pooler."""

import json

import asyncpg


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


POOL_MAX_SIZE = 10  # keep under the Supabase session pooler's per-database limit
COMMAND_TIMEOUT_SECONDS = 15  # a stuck query fails the request instead of hanging it


async def create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=POOL_MAX_SIZE,
        command_timeout=COMMAND_TIMEOUT_SECONDS,
        init=_init_connection,
    )
