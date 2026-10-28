"""get_player_stats: totals, per-90s and match list for one player, with optional splits."""

from typing import Any

import asyncpg

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import (
    SOURCE_API_FOOTBALL,
    ToolError,
    iso_utc,
)
from orchestrator.tools.lookups import require_player
from orchestrator.tools.results_freshness import results_success
from orchestrator.tools.stats_math import as_float, missing_warning, per90, sum_known

COUNT_STATS = (
    "goals",
    "assists",
    "shots",
    "shots_on_target",
    "yellow_cards",
    "red_cards",
    "fouls",
    "tackles",
    "key_passes",
)
EXPECTED_STATS = (("xg", "xG"), ("xa", "xA"))

# Appearances only (minutes > 0); newest first so LIMIT keeps the most recent.
_SQL = """
SELECT r.fixture_id, r.kickoff_at, r.venue, opp.name AS opponent, r.minutes,
       r.goals, r.assists, r.shots, r.shots_on_target, r.xg, r.xa, r.yellow_cards,
       r.red_cards, r.fouls, r.tackles, r.key_passes, r.fetched_at
FROM player_match_rows r
JOIN teams opp ON opp.id = r.opponent_id
WHERE r.player_id = $1
  AND r.season = $2
  AND r.minutes > 0
  AND ($3::text = 'all' OR r.venue = $3)
  AND ($4::bigint IS NULL OR r.opponent_id = $4)
ORDER BY r.kickoff_at DESC
LIMIT $5
"""


def _match(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "fixture_id": row["fixture_id"],
        "kickoff_at": iso_utc(row["kickoff_at"]),
        "opponent": row["opponent"],
        "venue": row["venue"],
        "minutes": row["minutes"],
        "goals": row["goals"],
        "assists": row["assists"],
        "shots": row["shots"],
        "xg": as_float(row["xg"]),
        "yellow_cards": row["yellow_cards"],
        "red_cards": row["red_cards"],
    }


def _summarise(rows: list[asyncpg.Record]) -> tuple[dict, dict, list[str]]:
    """(totals, per90, warnings) over the given appearances."""
    minutes = sum(r["minutes"] for r in rows)
    totals: dict[str, Any] = {k: sum(r[k] for r in rows) for k in COUNT_STATS}
    rates: dict[str, Any] = {k: per90(v, minutes) for k, v in totals.items()}
    warnings: list[str] = []
    for key, label in EXPECTED_STATS:
        total, missing = sum_known(r[key] for r in rows)
        known_minutes = sum(r["minutes"] for r in rows if r[key] is not None)
        totals[key] = None if total is None else round(total, 2)
        rates[key] = None if total is None else per90(total, known_minutes)
        warnings += missing_warning(label, missing, len(rows))
    return totals, rates, warnings


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    player = await require_player(ctx.conn, args["player_id"])
    filters = {
        "season": args["season"],
        "venue": args["venue"],
        "last_n": args.get("last_n"),
        "opponent_team_id": args.get("opponent_team_id"),
    }
    newest_first = await ctx.conn.fetch(
        _SQL,
        player["id"],
        filters["season"],
        filters["venue"],
        filters["opponent_team_id"],
        filters["last_n"],
    )
    if not newest_first:
        raise ToolError("no_data", f"No appearances for {player['name']} match these filters.")

    rows = list(reversed(newest_first))
    totals, rates, warnings = _summarise(rows)
    return await results_success(
        ctx,
        source=SOURCE_API_FOOTBALL,
        fetched_at=[r["fetched_at"] for r in rows],
        warnings=warnings,
        data={
            "player": player,
            "filters": filters,
            "appearances": len(rows),
            "minutes": sum(r["minutes"] for r in rows),
            "totals": totals,
            "per90": rates,
            "matches": [_match(r) for r in rows],
        },
    )
