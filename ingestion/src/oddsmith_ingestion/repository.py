"""Writes shared by jobs: create teams and players first seen in fixture data.

Existing rows are never overwritten here; seed_reference owns current clubs and names.
"""

from typing import Any

import asyncpg

from oddsmith_ingestion import mapping
from oddsmith_ingestion.reference_data import team_reference


async def ensure_teams(conn: asyncpg.Connection, raw_teams: list[dict[str, Any]]) -> dict[int, int]:
    """Insert teams missing from `teams` (with curated short name and aliases).
    `raw_teams` are API-Football team objects ({id, name, ...}). Returns provider_id -> id."""
    unique = {t["id"]: t for t in raw_teams}
    existing = await id_map(conn, "teams", list(unique))
    for provider_id, team in unique.items():
        if provider_id in existing:
            continue
        ref = team_reference(provider_id, team["name"])
        short_name = ref.short_name if ref else team["name"]
        aliases = list(dict.fromkeys([short_name, *(ref.aliases if ref else ())]))
        team_id = await conn.fetchval(
            """INSERT INTO teams (provider_id, name, short_name, aliases) VALUES ($1, $2, $3, $4)
               ON CONFLICT (provider_id) DO UPDATE SET provider_id = EXCLUDED.provider_id
               RETURNING id""",
            provider_id,
            team["name"],
            short_name,
            aliases,
        )
        await insert_aliases(conn, "team", team_id, [team["name"], *aliases])
        existing = {**existing, provider_id: team_id}
    return existing


async def ensure_players(
    conn: asyncpg.Connection, raw_players: list[tuple[int, str, str | None]]
) -> dict[int, int]:
    """Insert players missing from `players` with team_id NULL (seed_reference sets current
    clubs). `raw_players` are (provider_id, name, API-Football position). Returns id map."""
    unique = {pid: (name, pos) for pid, name, pos in raw_players}
    existing = await id_map(conn, "players", list(unique))
    for provider_id, (name, pos) in unique.items():
        if provider_id in existing:
            continue
        aliases = sorted(mapping.player_name_aliases(name) - {name})
        player_id = await conn.fetchval(
            """INSERT INTO players (provider_id, name, position, aliases) VALUES ($1, $2, $3, $4)
               ON CONFLICT (provider_id) DO UPDATE SET provider_id = EXCLUDED.provider_id
               RETURNING id""",
            provider_id,
            name,
            mapping.position(pos),
            aliases,
        )
        await insert_aliases(conn, "player", player_id, [name, *aliases])
        existing = {**existing, provider_id: player_id}
    return existing


async def insert_aliases(
    conn: asyncpg.Connection, entity_type: str, entity_id: int, aliases: list[str]
) -> None:
    by_search = {mapping.alias_search(a): a for a in reversed(aliases) if a}
    await conn.executemany(
        """INSERT INTO entity_aliases (alias, alias_search, entity_type, entity_id)
           VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING""",
        [(alias, search, entity_type, entity_id) for search, alias in by_search.items()],
    )


async def id_map(conn: asyncpg.Connection, table: str, provider_ids: list[int]) -> dict[int, int]:
    if table not in ("teams", "players", "fixtures"):
        raise ValueError(f"unexpected table {table!r}")
    rows = await conn.fetch(
        f"SELECT provider_id, id FROM {table} WHERE provider_id = ANY($1::int[])",  # noqa: S608
        provider_ids,
    )
    return {r["provider_id"]: r["id"] for r in rows}
