"""compare_to_market: Oddsmith's Poisson estimate vs the best bookmaker price. An estimate."""

from datetime import datetime, timedelta
from statistics import fmean
from typing import Any

import asyncpg

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import FRESHNESS_HOURS, ToolError, success
from orchestrator.tools.lookups import fixture_data, require_fixture_detail
from orchestrator.tools.odds_common import (
    Price,
    implied_probability,
    latest_prices,
    market_line,
    no_prices_error,
)
from orchestrator.tools.poisson import expected_goals, market_probabilities, score_matrix
from orchestrator.tools.results_freshness import results_state

ESTIMATE_WARNING = (
    "These are estimates from a simple model, not predictions: "
    "call them estimates when you quote them."
)
MISSING_RESULT_WARNING = (
    "A recent result isn't loaded yet, so the model's xG may be missing a match."
)

MODEL_NAME = "poisson_xg_last10_v1"
SOURCE = "Oddsmith model (API-Football xG, The Odds API prices)"
FORM_MATCHES = 10
MIN_FORM_MATCHES = 5
LEAGUE_WINDOW_DAYS = 365

_FORM_SQL = """
SELECT xg_for, xg_against, fetched_at
FROM team_match_rows
WHERE team_id = $1 AND kickoff_at < $2 AND xg_for IS NOT NULL AND xg_against IS NOT NULL
ORDER BY kickoff_at DESC
LIMIT $3
"""

# League-wide xG per team per match, split by venue, over the year before kick-off.
_LEAGUE_SQL = """
SELECT avg(xg_for) FILTER (WHERE venue = 'home') AS home_xg,
       avg(xg_for) FILTER (WHERE venue = 'away') AS away_xg
FROM team_match_rows
WHERE kickoff_at < $1 AND kickoff_at >= $2 AND xg_for IS NOT NULL
"""


async def _form(ctx: ToolContext, team_id: int, name: str, kickoff: datetime) -> list:
    rows = await ctx.conn.fetch(_FORM_SQL, team_id, kickoff, FORM_MATCHES)
    if len(rows) < MIN_FORM_MATCHES:
        raise ToolError("no_data", f"Not enough recent xG data for {name} to build an estimate.")
    return rows


async def _rates(ctx: ToolContext, fixture: asyncpg.Record) -> tuple[float, float, list, list]:
    kickoff = fixture["kickoff_at"]
    home = await _form(ctx, fixture["home_id"], fixture["home_name"], kickoff)
    away = await _form(ctx, fixture["away_id"], fixture["away_name"], kickoff)
    league = await ctx.conn.fetchrow(
        _LEAGUE_SQL, kickoff, kickoff - timedelta(days=LEAGUE_WINDOW_DAYS)
    )
    if league["home_xg"] is None or league["away_xg"] is None:
        raise ToolError("no_data", "Not enough league xG data to build an estimate.")

    def mean(rows: list, key: str) -> float:
        return fmean(float(r[key]) for r in rows)

    home_rate, away_rate = expected_goals(
        home_for=mean(home, "xg_for"),
        home_against=mean(home, "xg_against"),
        away_for=mean(away, "xg_for"),
        away_against=mean(away, "xg_against"),
        league_home=float(league["home_xg"]),
        league_away=float(league["away_xg"]),
    )
    return home_rate, away_rate, home, away


def _selection(selection: str, model_probability: float, prices: list[Price]) -> dict[str, Any]:
    best = prices[0]
    return {
        "selection": selection,
        "model_probability": round(model_probability, 4),
        "best_price": best.price,
        "best_bookmaker": best.bookmaker,
        "implied_probability": implied_probability(best.price),
        "edge": round(model_probability - 1 / best.price, 4),
    }


async def _xg_warnings(ctx: ToolContext, home: list, away: list) -> list[str]:
    """Decision 10: finished-match xG is never re-fetched, so its age says nothing once
    results are syncing; what matters is a result still missing after kick-off."""
    last_sync, missing = await results_state(ctx)
    if last_sync is not None:
        return [MISSING_RESULT_WARNING] if missing else []
    stats_cutoff = ctx.now - timedelta(hours=FRESHNESS_HOURS["stats"])
    newest_stats = max(r["fetched_at"] for r in [*home, *away])
    return (
        ["The xG data behind the model is over 48 hours old."]
        if newest_stats < stats_cutoff
        else []
    )


async def _warnings(ctx: ToolContext, home: list, away: list) -> list[str]:
    used = min(len(home), len(away))
    return [
        ESTIMATE_WARNING,
        *(
            [f"Model used {used} recent matches, not {FORM_MATCHES}."]
            if used < FORM_MATCHES
            else []
        ),
        *await _xg_warnings(ctx, home, away),
    ]


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    market, line = args["market"], market_line(args)
    fixture = await require_fixture_detail(ctx.conn, args["fixture_id"])
    if fixture["status"] != "scheduled":
        raise ToolError("unsupported", "Estimates are only available before kick-off.")
    prices = await latest_prices(ctx.conn, fixture["id"], market, line)
    if not prices:
        raise no_prices_error(market)

    home_rate, away_rate, home, away = await _rates(ctx, fixture)
    probabilities = market_probabilities(
        score_matrix(home_rate, away_rate), market, None if line is None else float(line)
    )
    return success(
        source=SOURCE,
        fetched_at=[p.captured_at for ps in prices.values() for p in ps],
        limit_hours=FRESHNESS_HOURS["odds"],
        now=ctx.now,
        warnings=await _warnings(ctx, home, away),
        data={
            "fixture": fixture_data(fixture),
            "model": {
                "name": MODEL_NAME,
                "expected_goals_home": round(home_rate, 2),
                "expected_goals_away": round(away_rate, 2),
                "matches_used": min(len(home), len(away)),
            },
            "selections": [_selection(s, probabilities[s], ps) for s, ps in prices.items()],
            "label": "estimate",
        },
    )
