"""get_fixtures: 2026/27 fixtures and results, filtered by team, opponent, matchweek or dates."""

from datetime import date
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
from orchestrator.tools.lookups import CURRENT_SEASON, team_ref

# Dates are UK calendar days. Which rows LIMIT keeps depends on status: the next scheduled,
# the latest finished, or (for 'all') the ones nearest now. Output is always in kickoff order.
_SQL = """
SELECT f.id, f.matchweek, f.kickoff_at, f.status, f.home_score, f.away_score, f.fetched_at,
       h.id AS home_id, h.name AS home_name, a.id AS away_id, a.name AS away_name
FROM fixtures f
JOIN teams h ON h.id = f.home_id
JOIN teams a ON a.id = f.away_id
WHERE f.season = $1
  AND ($2::bigint IS NULL OR $2 IN (f.home_id, f.away_id))
  AND ($3::bigint IS NULL OR $3 IN (f.home_id, f.away_id))
  AND ($4::int IS NULL OR f.matchweek = $4)
  AND ($5::date IS NULL OR (f.kickoff_at AT TIME ZONE 'Europe/London')::date >= $5)
  AND ($6::date IS NULL OR (f.kickoff_at AT TIME ZONE 'Europe/London')::date <= $6)
  AND ($7::text = 'all' OR f.status = $7)
ORDER BY CASE $7
           WHEN 'scheduled' THEN extract(epoch FROM f.kickoff_at)
           WHEN 'finished'  THEN -extract(epoch FROM f.kickoff_at)
           ELSE abs(extract(epoch FROM f.kickoff_at - $8::timestamptz))
         END,
         f.id
LIMIT $9
"""


def _parse_date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _fixture(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "fixture_id": row["id"],
        "matchweek": row["matchweek"],
        "kickoff_at": iso_utc(row["kickoff_at"]),
        "status": row["status"],
        "home": team_ref(row, "home_id", "home_name"),
        "away": team_ref(row, "away_id", "away_name"),
        "home_score": row["home_score"],
        "away_score": row["away_score"],
    }


def _check(args: dict[str, Any], date_from: date | None, date_to: date | None) -> None:
    team_id, opponent_id = args.get("team_id"), args.get("opponent_team_id")
    if team_id is not None and team_id == opponent_id:
        raise ToolError("invalid_input", "team_id and opponent_team_id must be different.")
    if date_from and date_to and date_from > date_to:
        raise ToolError("invalid_input", "date_from must be on or before date_to.")


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    date_from, date_to = _parse_date(args.get("date_from")), _parse_date(args.get("date_to"))
    _check(args, date_from, date_to)
    rows = await ctx.conn.fetch(
        _SQL,
        CURRENT_SEASON,
        args.get("team_id"),
        args.get("opponent_team_id"),
        args.get("matchweek"),
        date_from,
        date_to,
        args["status"],
        ctx.now,
        args["limit"],
    )
    if not rows:
        raise ToolError("no_data", "No fixtures match these filters.")

    in_kickoff_order = sorted(rows, key=lambda r: (r["kickoff_at"], r["id"]))
    return success(
        source=SOURCE_API_FOOTBALL,
        fetched_at=[r["fetched_at"] for r in rows],
        limit_hours=FRESHNESS_HOURS["fixtures"],
        now=ctx.now,
        data={"fixtures": [_fixture(r) for r in in_kickoff_order]},
    )
