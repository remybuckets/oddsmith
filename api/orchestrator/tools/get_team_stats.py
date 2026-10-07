"""get_team_stats: results, form and goal/card trends for one team, with optional splits."""

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
from orchestrator.tools.lookups import require_team
from orchestrator.tools.stats_math import as_float, missing_warning, rate, sum_known

OVER_LINE = 2.5

# Newest first so LIMIT keeps the most recent matches.
_SQL = """
SELECT r.fixture_id, r.kickoff_at, r.venue, opp.name AS opponent, r.goals_for,
       r.goals_against, r.xg_for, r.xg_against, r.corners, r.yellow_cards, r.red_cards,
       r.result, r.fetched_at
FROM team_match_rows r
JOIN teams opp ON opp.id = r.opponent_id
WHERE r.team_id = $1
  AND r.season = $2
  AND ($3::text = 'all' OR r.venue = $3)
ORDER BY r.kickoff_at DESC
LIMIT $4
"""


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _match(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "fixture_id": row["fixture_id"],
        "kickoff_at": iso_utc(row["kickoff_at"]),
        "opponent": row["opponent"],
        "venue": row["venue"],
        "goals_for": row["goals_for"],
        "goals_against": row["goals_against"],
        "xg_for": as_float(row["xg_for"]),
        "xg_against": as_float(row["xg_against"]),
        "result": row["result"],
    }


def _summarise(rows: list[asyncpg.Record]) -> tuple[dict[str, Any], list[str]]:
    played = len(rows)
    results = [r["result"] for r in rows]
    xg_for, missing_for = sum_known(r["xg_for"] for r in rows)
    xg_against, missing_against = sum_known(r["xg_against"] for r in rows)
    corners, missing_corners = sum_known(r["corners"] for r in rows)
    known_corners = played - missing_corners
    summary = {
        "played": played,
        "won": results.count("W"),
        "drawn": results.count("D"),
        "lost": results.count("L"),
        "form": "".join(results),
        "goals_for": sum(r["goals_for"] for r in rows),
        "goals_against": sum(r["goals_against"] for r in rows),
        "xg_for": _rounded(xg_for),
        "xg_against": _rounded(xg_against),
        "over_2_5": rate(
            sum(1 for r in rows if r["goals_for"] + r["goals_against"] > OVER_LINE), played
        ),
        "btts": rate(sum(1 for r in rows if r["goals_for"] and r["goals_against"]), played),
        "clean_sheets": rate(sum(1 for r in rows if r["goals_against"] == 0), played),
        "corners_per_match": None if corners is None else round(corners / known_corners, 2),
        "cards_per_match": round(sum(r["yellow_cards"] + r["red_cards"] for r in rows) / played, 2),
    }
    return summary, missing_warning("xG", max(missing_for, missing_against), played)


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    team = await require_team(ctx.conn, args["team_id"])
    filters = {"season": args["season"], "venue": args["venue"], "last_n": args.get("last_n")}
    newest_first = await ctx.conn.fetch(
        _SQL, team["id"], filters["season"], filters["venue"], filters["last_n"]
    )
    if not newest_first:
        raise ToolError("no_data", f"No matches for {team['name']} match these filters.")

    rows = list(reversed(newest_first))
    summary, warnings = _summarise(rows)
    return success(
        source=SOURCE_API_FOOTBALL,
        fetched_at=[r["fetched_at"] for r in rows],
        limit_hours=FRESHNESS_HOURS["stats"],
        now=ctx.now,
        warnings=warnings,
        data={"team": team, "filters": filters, **summary, "matches": [_match(r) for r in rows]},
    )
