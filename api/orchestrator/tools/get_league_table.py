"""get_league_table: the 2026/27 table from finished matches, optionally home or away only."""

from typing import Any

import asyncpg

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import FRESHNESS_HOURS, SOURCE_API_FOOTBALL, ToolError, success
from orchestrator.tools.lookups import CURRENT_SEASON, team_ref

POINTS = {"W": 3, "D": 1, "L": 0}
FORM_LENGTH = 5

# Finished matches without both team rows would leave `played` short for someone.
_INCOMPLETE_SQL = """
SELECT count(*)
FROM fixtures f
WHERE f.season = $1
  AND f.status = 'finished'
  AND (SELECT count(*) FROM team_match_stats tms WHERE tms.fixture_id = f.id) < 2
"""

_SQL = """
SELECT t.id, t.name,
       count(*)                                    AS played,
       count(*) FILTER (WHERE r.result = 'W')      AS won,
       count(*) FILTER (WHERE r.result = 'D')      AS drawn,
       count(*) FILTER (WHERE r.result = 'L')      AS lost,
       sum(r.goals_for)                            AS goals_for,
       sum(r.goals_against)                        AS goals_against,
       array_agg(r.result ORDER BY r.kickoff_at DESC) AS results_newest_first,
       min(r.fetched_at)                           AS oldest_fetched_at
FROM team_match_rows r
JOIN teams t ON t.id = r.team_id
WHERE r.season = $1
  AND ($2::text = 'all' OR r.venue = $2)
GROUP BY t.id, t.name
"""


def _row(record: asyncpg.Record) -> dict[str, Any]:
    goals_for, goals_against = int(record["goals_for"]), int(record["goals_against"])
    recent = record["results_newest_first"][:FORM_LENGTH]
    return {
        "team": team_ref(record),
        "played": record["played"],
        "won": record["won"],
        "drawn": record["drawn"],
        "lost": record["lost"],
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_difference": goals_for - goals_against,
        "points": record["won"] * POINTS["W"] + record["drawn"] * POINTS["D"],
        "form": "".join(reversed(recent)),
    }


def _standing_key(row: dict[str, Any]) -> tuple:
    return (-row["points"], -row["goal_difference"], -row["goals_for"], row["team"]["name"])


def _incomplete_warning(count: int) -> list[str]:
    if not count:
        return []
    matches = "match" if count == 1 else "matches"
    return [f"Team stats missing for {count} finished {matches}, so the table may be incomplete."]


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    venue = args["venue"]
    records = await ctx.conn.fetch(_SQL, CURRENT_SEASON, venue)
    if not records:
        raise ToolError("no_data", "No finished matches yet this season.")

    standings = sorted((_row(r) for r in records), key=_standing_key)
    rows = [{"position": i, **row} for i, row in enumerate(standings, start=1)]
    incomplete = await ctx.conn.fetchval(_INCOMPLETE_SQL, CURRENT_SEASON)
    return success(
        source=SOURCE_API_FOOTBALL,
        fetched_at=[r["oldest_fetched_at"] for r in records],
        limit_hours=FRESHNESS_HOURS["stats"],
        now=ctx.now,
        warnings=_incomplete_warning(incomplete),
        data={"venue": venue, "rows": rows},
    )
