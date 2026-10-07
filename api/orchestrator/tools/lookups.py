"""Shared lookups: existence checks and the entity refs the contract's $defs describe."""

from typing import Any

import asyncpg

from orchestrator.tools.envelope import ToolError

CURRENT_SEASON = "2026/27"


def team_ref(row: asyncpg.Record, id_key: str = "id", name_key: str = "name") -> dict[str, Any]:
    return {"id": row[id_key], "name": row[name_key]}


def player_ref(row: asyncpg.Record) -> dict[str, Any]:
    """entity_ref_with_team from a row with id, name, team_id and team_name."""
    return {
        "id": row["id"],
        "name": row["name"],
        "team_id": row["team_id"],
        "team_name": row["team_name"],
    }


async def require_team(conn: asyncpg.Connection, team_id: int) -> dict[str, Any]:
    row = await conn.fetchrow("SELECT id, name FROM teams WHERE id = $1", team_id)
    if row is None:
        raise ToolError("not_found", f"No team with id {team_id}. Use resolve_entity first.")
    return team_ref(row)


async def require_player(conn: asyncpg.Connection, player_id: int) -> dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT p.id, p.name, p.team_id, t.name AS team_name"
        " FROM players p LEFT JOIN teams t ON t.id = p.team_id WHERE p.id = $1",
        player_id,
    )
    if row is None:
        raise ToolError("not_found", f"No player with id {player_id}. Use resolve_entity first.")
    return player_ref(row)


async def require_fixture(conn: asyncpg.Connection, fixture_id: int) -> asyncpg.Record:
    row = await conn.fetchrow("SELECT id, home_id, away_id FROM fixtures WHERE id = $1", fixture_id)
    if row is None:
        raise ToolError("not_found", f"No fixture with id {fixture_id}. Use get_fixtures first.")
    return row
