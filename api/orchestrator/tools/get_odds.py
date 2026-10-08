"""get_odds: current prices for one fixture and market, with the best price per selection."""

from typing import Any

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import FRESHNESS_HOURS, success
from orchestrator.tools.lookups import fixture_data, require_fixture_detail
from orchestrator.tools.odds_common import (
    SOURCE_ODDS_API,
    Price,
    implied_probability,
    latest_prices,
    market_line,
    no_prices_error,
)

KICKED_OFF_WARNING = "Kick-off has passed; these are the last pre-match prices."


def _selection(selection: str, prices: list[Price]) -> dict[str, Any]:
    best = prices[0]
    return {
        "selection": selection,
        "best_price": best.price,
        "best_bookmaker": best.bookmaker,
        "implied_probability": implied_probability(best.price),
        "prices": [p.as_dict() for p in prices],
    }


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    market, line = args["market"], market_line(args)
    fixture = await require_fixture_detail(ctx.conn, args["fixture_id"])
    prices = await latest_prices(ctx.conn, fixture["id"], market, line)
    if not prices:
        raise no_prices_error(market)

    overround = sum(1 / p[0].price for p in prices.values())
    return success(
        source=SOURCE_ODDS_API,
        fetched_at=[p.captured_at for ps in prices.values() for p in ps],
        limit_hours=FRESHNESS_HOURS["odds"],
        now=ctx.now,
        warnings=[] if fixture["status"] == "scheduled" else [KICKED_OFF_WARNING],
        data={
            "fixture": fixture_data(fixture),
            "market": market,
            "line": None if line is None else float(line),
            "selections": [_selection(s, ps) for s, ps in prices.items()],
            "overround": round(overround, 4),
        },
    )
