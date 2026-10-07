"""get_availability: current injuries, suspensions and doubts for a fixture, team or player."""

from typing import Any

import asyncpg

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import (
    FRESHNESS_HOURS,
    SOURCE_API_FOOTBALL,
    ToolError,
    iso_utc,
    success,
)
from orchestrator.tools.lookups import player_ref, require_fixture, require_player, require_team

SYNC_JOB = "sync_availability"
PRESUMED_AVAILABLE = "Players not listed are presumed available."

# availability.source values -> citation labels.
SOURCE_LABELS = {"api-football": SOURCE_API_FOOTBALL}

# The team shown is the one the absence is recorded against.
_SQL = """
SELECT p.id, p.name, av.team_id, t.name AS team_name, av.status, av.reason,
       av.expected_return, av.source, av.updated_at, av.fetched_at
FROM availability av
JOIN players p ON p.id = av.player_id
JOIN teams t   ON t.id = av.team_id
WHERE ($1::bigint[] IS NULL OR av.team_id = ANY($1))
  AND ($2::bigint IS NULL OR av.team_id = $2)
  AND ($3::bigint IS NULL OR av.player_id = $3)
ORDER BY t.name, p.name
"""

_LAST_SYNC_SQL = """
SELECT max(finished_at) FROM job_runs WHERE name = $1 AND status = 'success'
"""


def _label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def _entry(row: asyncpg.Record) -> dict[str, Any]:
    expected_return = row["expected_return"]
    return {
        "player": player_ref(row),
        "status": row["status"],
        "reason": row["reason"],
        "expected_return": None if expected_return is None else expected_return.isoformat(),
        "source": _label(row["source"]),
        "updated_at": iso_utc(row["updated_at"]),
    }


async def _fixture_team_ids(ctx: ToolContext, fixture_id: int | None) -> list[int] | None:
    if fixture_id is None:
        return None
    fixture = await require_fixture(ctx.conn, fixture_id)
    return [fixture["home_id"], fixture["away_id"]]


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    team_id, player_id = args.get("team_id"), args.get("player_id")
    fixture_team_ids = await _fixture_team_ids(ctx, args.get("fixture_id"))
    if team_id is not None:
        await require_team(ctx.conn, team_id)
    if player_id is not None:
        await require_player(ctx.conn, player_id)

    rows = await ctx.conn.fetch(_SQL, fixture_team_ids, team_id, player_id)
    last_sync = await ctx.conn.fetchval(_LAST_SYNC_SQL, SYNC_JOB)
    fetched_at = [r["fetched_at"] for r in rows] + ([last_sync] if last_sync else [])
    if not fetched_at:
        raise ToolError("no_data", "Injury and suspension data has not been loaded yet.")

    sources = sorted({_label(r["source"]) for r in rows}) or [SOURCE_API_FOOTBALL]
    return success(
        source=", ".join(sources),
        fetched_at=fetched_at,
        limit_hours=FRESHNESS_HOURS["availability"],
        now=ctx.now,
        warnings=[PRESUMED_AVAILABLE],
        data={"entries": [_entry(r) for r in rows]},
    )
