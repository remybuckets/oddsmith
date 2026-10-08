import pytest

from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio


async def odds(ctx, **args):
    return await run_tool(ctx, "get_odds", args)


async def movement(ctx, **args):
    return await run_tool(ctx, "get_odds_movement", args)


def by_selection(result):
    return {s["selection"]: s for s in result["data"]["selections"]}


async def test_best_price_per_selection_from_latest_snapshots(ctx):
    result = await odds(ctx, fixture_id=201, market="h2h")

    assert result["ok"] is True
    selections = result["data"]["selections"]
    assert [s["selection"] for s in selections] == ["home", "draw", "away"]
    home = selections[0]
    assert (home["best_price"], home["best_bookmaker"]) == (2.25, "Coral")
    assert home["implied_probability"] == 0.4444
    assert [(p["bookmaker"], p["price"]) for p in home["prices"]] == [
        ("Coral", 2.25),
        ("Sky Bet", 2.2),
        ("William Hill", 2.1),
    ]
    assert home["prices"][0]["captured_at"] == "2026-10-07T10:00:00Z"
    assert by_selection(result)["away"]["best_bookmaker"] == "William Hill"
    assert result["data"]["overround"] == 1.0332


async def test_disabled_bookmakers_are_ignored(ctx):
    result = await odds(ctx, fixture_id=201, market="h2h")

    bookmakers = {p["bookmaker"] for s in result["data"]["selections"] for p in s["prices"]}
    assert "Paddy Power" not in bookmakers


async def test_fixture_and_freshness(ctx):
    result = await odds(ctx, fixture_id=201, market="h2h")

    fixture = result["data"]["fixture"]
    assert fixture["fixture_id"] == 201
    assert fixture["home"] == {"id": 3, "name": "Aston Villa", "short_name": "AVL"}
    assert result["source"] == "The Odds API"
    assert result["as_of"] == "2026-10-07T10:00:00Z"
    assert result["freshness_limit_hours"] == 6
    assert result["is_stale"] is False
    assert result["data"]["line"] is None


async def test_totals_needs_a_line(ctx):
    result = await odds(ctx, fixture_id=201, market="totals")
    assert result["error"]["code"] == "invalid_input"


async def test_totals_with_line(ctx):
    result = await odds(ctx, fixture_id=201, market="totals", line=2.5)

    assert result["data"]["line"] == 2.5
    assert [(s["selection"], s["best_price"]) for s in result["data"]["selections"]] == [
        ("over", 1.85),
        ("under", 2.0),
    ]


async def test_line_without_prices_is_no_data(ctx):
    result = await odds(ctx, fixture_id=201, market="totals", line=3.5)
    assert result["error"]["code"] == "no_data"


async def test_btts_without_prices_is_no_data(ctx):
    result = await odds(ctx, fixture_id=201, market="btts")

    assert result["error"]["code"] == "no_data"
    assert "both teams to score" in result["error"]["message"].lower()


async def test_old_prices_are_stale(ctx):
    result = await odds(ctx, fixture_id=202, market="h2h")

    assert result["is_stale"] is True
    assert result["as_of"] == "2026-10-06T06:00:00Z"


async def test_unknown_fixture_is_not_found(ctx):
    result = await odds(ctx, fixture_id=99999, market="h2h")
    assert result["error"]["code"] == "not_found"


async def test_shortening_price_is_steam(ctx):
    result = await movement(ctx, fixture_id=201, market="h2h", selection="home")

    data = result["data"]
    assert (data["opening_price"], data["current_price"]) == (2.5, 2.25)
    assert data["change_pct"] == -10.0
    assert data["direction"] == "steam"
    assert data["series"] == [
        {"captured_at": "2026-10-06T10:00:00Z", "best_price": 2.5, "bookmaker": "Sky Bet"},
        {"captured_at": "2026-10-07T10:00:00Z", "best_price": 2.25, "bookmaker": "Coral"},
    ]
    assert result["as_of"] == "2026-10-07T10:00:00Z"
    assert result["freshness_limit_hours"] == 6


async def test_lengthening_price_is_drift(ctx):
    result = await movement(ctx, fixture_id=201, market="h2h", selection="away")

    assert result["data"]["change_pct"] == 6.5
    assert result["data"]["direction"] == "drift"


async def test_unchanged_price_is_stable(ctx):
    result = await movement(ctx, fixture_id=201, market="h2h", selection="draw")
    assert result["data"]["direction"] == "stable"


async def test_window_excludes_older_snapshots(ctx):
    result = await movement(ctx, fixture_id=201, market="h2h", selection="home", hours=12)

    assert [p["captured_at"] for p in result["data"]["series"]] == ["2026-10-07T10:00:00Z"]
    assert result["data"]["direction"] == "stable"


async def test_no_snapshots_in_window_is_no_data(ctx):
    result = await movement(ctx, fixture_id=201, market="h2h", selection="home", hours=1)
    assert result["error"]["code"] == "no_data"


async def test_selection_must_belong_to_market(ctx):
    result = await movement(ctx, fixture_id=201, market="h2h", selection="over")
    assert result["error"]["code"] == "invalid_input"
