"""Shared odds logic: markets, lines and the latest prices from enabled bookmakers."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import asyncpg

from orchestrator.tools.envelope import ToolError, iso_utc

SOURCE_ODDS_API = "The Odds API"

MARKET_SELECTIONS = {
    "h2h": ("home", "draw", "away"),
    "totals": ("over", "under"),
    "btts": ("yes", "no"),
}
MARKET_NAMES = {"h2h": "match result", "totals": "total goals", "btts": "both teams to score"}

# Latest price per enabled bookmaker; best first, ties broken by the bookmakers' display order.
_LATEST_SQL = """
SELECT o.selection, o.price, o.captured_at, b.display_name
FROM odds_latest o
JOIN bookmakers b ON b.key = o.bookmaker AND b.is_enabled
WHERE o.fixture_id = $1
  AND o.market = $2
  AND o.line IS NOT DISTINCT FROM $3::numeric
ORDER BY o.selection, o.price DESC, b.sort_order
"""


@dataclass(frozen=True)
class Price:
    bookmaker: str
    price: float
    captured_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "bookmaker": self.bookmaker,
            "price": self.price,
            "captured_at": iso_utc(self.captured_at),
        }


def market_line(args: dict[str, Any]) -> Decimal | None:
    """The line to query: required for totals, ignored for markets without one."""
    if args["market"] != "totals":
        return None
    if args.get("line") is None:
        raise ToolError("invalid_input", "line is required for totals, e.g. 2.5.")
    return Decimal(str(args["line"]))


def check_selection(market: str, selection: str) -> None:
    allowed = MARKET_SELECTIONS[market]
    if selection not in allowed:
        raise ToolError(
            "invalid_input", f"{selection} is not a {market} selection; use {', '.join(allowed)}."
        )


def no_prices_error(market: str) -> ToolError:
    return ToolError(
        "no_data",
        f"No current {MARKET_NAMES[market]} prices for this fixture. Both teams to score prices "
        "are only loaded on matchday.",
    )


async def latest_prices(
    conn: asyncpg.Connection, fixture_id: int, market: str, line: Decimal | None
) -> dict[str, list[Price]]:
    """Best-first prices per selection, in the market's usual selection order."""
    rows = await conn.fetch(_LATEST_SQL, fixture_id, market, line)
    grouped = {
        selection: [
            Price(r["display_name"], float(r["price"]), r["captured_at"])
            for r in rows
            if r["selection"] == selection
        ]
        for selection in MARKET_SELECTIONS[market]
    }
    return {selection: prices for selection, prices in grouped.items() if prices}


def implied_probability(price: float) -> float:
    return round(1 / price, 4)
