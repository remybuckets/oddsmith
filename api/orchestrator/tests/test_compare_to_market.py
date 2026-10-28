import math
from datetime import timedelta

import pytest

from orchestrator.tests.seed import NOW
from orchestrator.tools import run_tool
from orchestrator.tools.context import ToolContext
from orchestrator.tools.poisson import expected_goals, market_probabilities, score_matrix


def test_equal_rates_give_symmetric_result():
    probs = market_probabilities(score_matrix(1.0, 1.0), "h2h", None)

    assert probs["home"] == pytest.approx(probs["away"])
    assert sum(probs.values()) == pytest.approx(1.0)
    assert probs["draw"] == pytest.approx(0.3085, abs=1e-4)


def test_totals_use_the_total_goal_distribution():
    # Total goals ~ Poisson(2): P(<=2) = e^-2 * (1 + 2 + 2)
    probs = market_probabilities(score_matrix(1.0, 1.0), "totals", 2.5)

    assert probs["under"] == pytest.approx(5 * math.exp(-2), abs=1e-6)
    assert probs["over"] == pytest.approx(1 - 5 * math.exp(-2), abs=1e-6)


def test_btts_is_both_teams_scoring():
    probs = market_probabilities(score_matrix(1.0, 1.0), "btts", None)

    assert probs["yes"] == pytest.approx((1 - math.exp(-1)) ** 2, abs=1e-6)
    assert probs["no"] == pytest.approx(1 - probs["yes"])


def test_average_teams_score_the_league_venue_averages():
    home, away = expected_goals(
        home_for=1.3,
        home_against=1.3,
        away_for=1.3,
        away_against=1.3,
        league_home=1.5,
        league_away=1.1,
    )
    assert (home, away) == pytest.approx((1.5, 1.1))


def test_stronger_attack_raises_expected_goals():
    home, _ = expected_goals(
        home_for=2.6,
        home_against=1.3,
        away_for=1.3,
        away_against=1.3,
        league_home=1.5,
        league_away=1.1,
    )
    assert home == pytest.approx(3.0)


async def compare(ctx, **args):
    return await run_tool(ctx, "compare_to_market", args)


@pytest.mark.asyncio
async def test_model_vs_market_for_match_result(ctx):
    result = await compare(ctx, fixture_id=201, market="h2h")

    assert result["ok"] is True
    data = result["data"]
    assert data["label"] == "estimate"
    assert data["model"]["name"] == "poisson_xg_last10_v1"
    assert data["model"]["matches_used"] == 5
    assert data["model"]["expected_goals_home"] > 0
    selections = {s["selection"]: s for s in data["selections"]}
    assert set(selections) == {"home", "draw", "away"}
    assert sum(s["model_probability"] for s in selections.values()) == pytest.approx(1, abs=1e-3)
    home = selections["home"]
    assert (home["best_price"], home["best_bookmaker"]) == (2.25, "Coral")
    assert home["implied_probability"] == 0.4444
    assert home["edge"] == pytest.approx(home["model_probability"] - 0.4444, abs=1e-4)


@pytest.mark.asyncio
async def test_freshness_follows_the_odds_and_warns_on_short_history(ctx):
    result = await compare(ctx, fixture_id=201, market="h2h")

    assert result["source"] == "Oddsmith model (API-Football xG, The Odds API prices)"
    assert result["as_of"] == "2026-10-07T10:00:00Z"
    assert result["freshness_limit_hours"] == 6
    assert result["is_stale"] is False
    assert "Model used 5 recent matches, not 10." in result["warnings"]


@pytest.mark.asyncio
async def test_every_comparison_asks_for_the_figures_to_be_called_estimates(ctx):
    # Eval regression (run 8, v03 and c02): model figures quoted without the word
    # "estimate", though the prompt asks for it.
    result = await compare(ctx, fixture_id=201, market="totals", line=2.5)

    assert result["warnings"][0] == (
        "These are estimates from a simple model, not predictions: "
        "call them estimates when you quote them."
    )


THREE_DAYS_ON = NOW + timedelta(days=3)  # seeded xG rows are then over 48 hours old
OLD_XG = "The xG data behind the model is over 48 hours old."
MISSING_RESULT = "A recent result isn't loaded yet, so the model's xG may be missing a match."


async def _results_synced(conn):
    await conn.execute(
        "INSERT INTO job_runs (name, started_at, finished_at, status)"
        " VALUES ('sync_results', $1, $1, 'success')",
        THREE_DAYS_ON - timedelta(hours=5),
    )


@pytest.mark.asyncio
async def test_xg_is_not_called_old_while_results_are_up_to_date(conn):
    # Eval regression (run 7, v02): finished-match xG is never re-fetched, so "over 48
    # hours old" fired between every matchweek (decision 10).
    await _results_synced(conn)
    later = ToolContext(conn=conn, now=THREE_DAYS_ON)

    result = await compare(later, fixture_id=201, market="h2h")

    assert OLD_XG not in result["warnings"]
    assert MISSING_RESULT not in result["warnings"]


@pytest.mark.asyncio
async def test_xg_warns_when_a_result_is_missing_after_kick_off(conn):
    await _results_synced(conn)
    await conn.execute(
        "INSERT INTO fixtures (id, provider_id, season, matchweek, home_id, away_id,"
        " kickoff_at, status) VALUES (999, 9999, '2026/27', 4, 4, 5, $1, 'live')",
        THREE_DAYS_ON - timedelta(hours=4),
    )
    later = ToolContext(conn=conn, now=THREE_DAYS_ON)

    result = await compare(later, fixture_id=201, market="h2h")

    assert MISSING_RESULT in result["warnings"]


@pytest.mark.asyncio
async def test_without_a_results_sync_old_xg_is_still_flagged(conn):
    result = await compare(ToolContext(conn=conn, now=THREE_DAYS_ON), fixture_id=201, market="h2h")

    assert OLD_XG in result["warnings"]


@pytest.mark.asyncio
async def test_totals_compare(ctx):
    result = await compare(ctx, fixture_id=201, market="totals", line=2.5)

    selections = {s["selection"]: s for s in result["data"]["selections"]}
    assert set(selections) == {"over", "under"}
    total = selections["over"]["model_probability"] + selections["under"]["model_probability"]
    assert total == pytest.approx(1, abs=1e-3)


@pytest.mark.asyncio
async def test_no_prices_is_no_data(ctx):
    result = await compare(ctx, fixture_id=201, market="btts")
    assert result["error"]["code"] == "no_data"


@pytest.mark.asyncio
async def test_finished_fixture_is_unsupported(ctx):
    result = await compare(ctx, fixture_id=102, market="h2h")
    assert result["error"]["code"] == "unsupported"


@pytest.mark.asyncio
async def test_too_little_history_is_no_data(ctx, conn):
    await conn.execute("DELETE FROM team_match_stats WHERE team_id = 3 AND fixture_id <> 102")

    result = await compare(ctx, fixture_id=201, market="h2h")
    assert result["error"]["code"] == "no_data"
    assert "Aston Villa" in result["error"]["message"]


def test_unknown_market_is_rejected():
    with pytest.raises(ValueError):
        market_probabilities(score_matrix(1.0, 1.0), "corners", None)


@pytest.mark.asyncio
async def test_no_league_xg_in_the_window_is_no_data(ctx, conn, monkeypatch):
    from orchestrator.tools import compare_to_market

    monkeypatch.setattr(compare_to_market, "LEAGUE_WINDOW_DAYS", 0)

    result = await compare(ctx, fixture_id=201, market="h2h")
    assert result["error"]["code"] == "no_data"
