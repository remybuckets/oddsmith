"""Shared lookups: existence checks and the entity refs the contract's $defs describe."""

from typing import Any

import asyncpg

from orchestrator.tools.envelope import ToolError, iso_utc

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


# Fixture with both teams' short names, which the answer cards' TeamRef needs.
_FIXTURE_DETAIL_SQL = """
SELECT f.id, f.matchweek, f.kickoff_at, f.status, f.home_score, f.away_score, f.fetched_at,
       f.home_id, h.name AS home_name, h.short_name AS home_short_name,
       f.away_id, a.name AS away_name, a.short_name AS away_short_name
FROM fixtures f
JOIN teams h ON h.id = f.home_id
JOIN teams a ON a.id = f.away_id
WHERE f.id = $1
"""


async def require_fixture_detail(conn: asyncpg.Connection, fixture_id: int) -> asyncpg.Record:
    row = await conn.fetchrow(_FIXTURE_DETAIL_SQL, fixture_id)
    if row is None:
        raise ToolError("not_found", f"No fixture with id {fixture_id}. Use get_fixtures first.")
    return row


def fixture_data(row: asyncpg.Record) -> dict[str, Any]:
    """The contract's $defs/fixture, with short_name on each team."""

    def team(side: str) -> dict[str, Any]:
        return {
            "id": row[f"{side}_id"],
            "name": row[f"{side}_name"],
            "short_name": row[f"{side}_short_name"],
        }

    return {
        "fixture_id": row["id"],
        "matchweek": row["matchweek"],
        "kickoff_at": iso_utc(row["kickoff_at"]),
        "status": row["status"],
        "home": team("home"),
        "away": team("away"),
        "home_score": row["home_score"],
        "away_score": row["away_score"],
    }
