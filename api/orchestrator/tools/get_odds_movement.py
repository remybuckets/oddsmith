"""get_odds_movement: how the best price on one selection has moved over recent hours."""

from datetime import timedelta
from typing import Any

import asyncpg

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import FRESHNESS_HOURS, ToolError, iso_utc, success
from orchestrator.tools.lookups import require_fixture
from orchestrator.tools.odds_common import SOURCE_ODDS_API, check_selection, market_line

# A move smaller than this (in %) either way is 'stable'.
STABLE_CHANGE_PCT = 2.0

# For each sweep in the window, the best price across enabled bookmakers, using each
# bookmaker's latest price at that moment (a bookmaker may be missing from a sweep).
_SQL = """
WITH snaps AS (
    SELECT s.price, s.captured_at, s.bookmaker, b.display_name, b.sort_order
    FROM odds_snapshots s
    JOIN bookmakers b ON b.key = s.bookmaker AND b.is_enabled
    WHERE s.fixture_id = $1
      AND s.market = $2
      AND s.line IS NOT DISTINCT FROM $3::numeric
      AND s.selection = $4
),
sweeps AS (
    SELECT DISTINCT captured_at FROM snaps WHERE captured_at >= $5
)
SELECT sw.captured_at, best.price, best.display_name
FROM sweeps sw
CROSS JOIN LATERAL (
    SELECT latest.price, latest.display_name
    FROM (
        SELECT DISTINCT ON (s.bookmaker) s.price, s.display_name, s.sort_order
        FROM snaps s
        WHERE s.captured_at <= sw.captured_at
        ORDER BY s.bookmaker, s.captured_at DESC
    ) latest
    ORDER BY latest.price DESC, latest.sort_order
    LIMIT 1
) best
ORDER BY sw.captured_at
"""


def _direction(change_pct: float) -> str:
    if change_pct < -STABLE_CHANGE_PCT:
        return "steam"
    if change_pct > STABLE_CHANGE_PCT:
        return "drift"
    return "stable"


def _point(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "captured_at": iso_utc(row["captured_at"]),
        "best_price": float(row["price"]),
        "bookmaker": row["display_name"],
    }


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    market, selection, line = args["market"], args["selection"], market_line(args)
    check_selection(market, selection)
    fixture = await require_fixture(ctx.conn, args["fixture_id"])
    since = ctx.now - timedelta(hours=args["hours"])
    rows = await ctx.conn.fetch(_SQL, fixture["id"], market, line, selection, since)
    if not rows:
        raise ToolError("no_data", f"No {selection} prices in the last {args['hours']} hours.")

    opening, current = float(rows[0]["price"]), float(rows[-1]["price"])
    change_pct = round((current - opening) / opening * 100, 1)
    # Freshness is about the current price, the last sweep, not the start of the window.
    return success(
        source=SOURCE_ODDS_API,
        fetched_at=[rows[-1]["captured_at"]],
        limit_hours=FRESHNESS_HOURS["odds"],
        now=ctx.now,
        data={
            "selection": selection,
            "opening_price": opening,
            "current_price": current,
            "change_pct": change_pct,
            "direction": _direction(change_pct),
            "series": [_point(r) for r in rows],
        },
    )
