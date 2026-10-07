"""get_head_to_head: past meetings between two teams, a summary and who gets booked in them."""

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
from orchestrator.tools.lookups import player_ref, require_team
from orchestrator.tools.stats_math import rate

OVER_LINE = 2.5
MOST_BOOKED_LIMIT = 10

_MEETINGS_SQL = """
SELECT f.id, f.kickoff_at, f.home_id, h.name AS home, a.name AS away, f.home_score,
       f.away_score, f.fetched_at,
       (SELECT CASE WHEN count(*) = 2 THEN sum(tms.yellow_cards + tms.red_cards) END
        FROM team_match_stats tms WHERE tms.fixture_id = f.id) AS total_cards
FROM fixtures f
JOIN teams h ON h.id = f.home_id
JOIN teams a ON a.id = f.away_id
WHERE f.status = 'finished'
  AND f.home_score IS NOT NULL AND f.away_score IS NOT NULL
  AND ((f.home_id = $1 AND f.away_id = $2) OR (f.home_id = $2 AND f.away_id = $1))
ORDER BY f.kickoff_at DESC
LIMIT $3
"""

# Team shown is the player's current club.
_BOOKINGS_SQL = """
SELECT p.id, p.name, p.team_id, t.name AS team_name,
       count(*) FILTER (WHERE r.minutes > 0) AS appearances,
       sum(r.yellow_cards)                   AS yellow_cards,
       sum(r.red_cards)                      AS red_cards,
       min(r.fetched_at)                     AS oldest_fetched_at
FROM player_match_rows r
JOIN players p     ON p.id = r.player_id
LEFT JOIN teams t  ON t.id = p.team_id
WHERE r.fixture_id = ANY($1::bigint[])
GROUP BY p.id, p.name, p.team_id, t.name
HAVING sum(r.yellow_cards + r.red_cards) > 0
ORDER BY sum(r.yellow_cards + r.red_cards) DESC, sum(r.red_cards) DESC, p.name
LIMIT $2
"""


def _meeting(row: asyncpg.Record) -> dict[str, Any]:
    total_cards = row["total_cards"]
    return {
        "fixture_id": row["id"],
        "kickoff_at": iso_utc(row["kickoff_at"]),
        "home": row["home"],
        "away": row["away"],
        "home_score": row["home_score"],
        "away_score": row["away_score"],
        "total_cards": None if total_cards is None else int(total_cards),
    }


def _summary(rows: list[asyncpg.Record], team_a_id: int) -> dict[str, Any]:
    margins = [
        (r["home_score"] - r["away_score"]) * (1 if r["home_id"] == team_a_id else -1) for r in rows
    ]
    totals = [r["home_score"] + r["away_score"] for r in rows]
    played = len(rows)
    return {
        "played": played,
        "team_a_wins": sum(1 for m in margins if m > 0),
        "draws": margins.count(0),
        "team_b_wins": sum(1 for m in margins if m < 0),
        "avg_goals": round(sum(totals) / played, 2),
        "over_2_5": rate(sum(1 for t in totals if t > OVER_LINE), played),
        "btts": rate(sum(1 for r in rows if r["home_score"] and r["away_score"]), played),
    }


def _booking(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "player": player_ref(row),
        "appearances": row["appearances"],
        "yellow_cards": int(row["yellow_cards"]),
        "red_cards": int(row["red_cards"]),
    }


async def _bookings(ctx: ToolContext, fixture_ids: list[int]) -> list[asyncpg.Record]:
    return await ctx.conn.fetch(_BOOKINGS_SQL, fixture_ids, MOST_BOOKED_LIMIT)


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if args["team_a_id"] == args["team_b_id"]:
        raise ToolError("invalid_input", "team_a_id and team_b_id must be different teams.")
    team_a = await require_team(ctx.conn, args["team_a_id"])
    team_b = await require_team(ctx.conn, args["team_b_id"])
    rows = await ctx.conn.fetch(_MEETINGS_SQL, team_a["id"], team_b["id"], args["limit"])
    if not rows:
        raise ToolError(
            "no_data",
            f"No Premier League meetings between {team_a['name']} and "
            f"{team_b['name']} since 2025/26.",
        )

    booked = await _bookings(ctx, [r["id"] for r in rows]) if args["include_bookings"] else []
    bookings = {"most_booked": [_booking(b) for b in booked]} if args["include_bookings"] else {}
    return success(
        source=SOURCE_API_FOOTBALL,
        fetched_at=[r["fetched_at"] for r in rows] + [b["oldest_fetched_at"] for b in booked],
        limit_hours=FRESHNESS_HOURS["stats"],
        now=ctx.now,
        data={
            "team_a": team_a,
            "team_b": team_b,
            "meetings": [_meeting(r) for r in rows],
            "summary": _summary(rows, team_a["id"]),
            **bookings,
        },
    )
