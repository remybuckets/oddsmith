import pytest

from orchestrator.cards import ToolOutcome, build_cards, collect_sources, selection_label
from orchestrator.tests.openapi import assert_matches
from orchestrator.tests.seed import BRE, SAKA
from orchestrator.tools import run_tool

pytestmark = pytest.mark.asyncio

THRESHOLD = 0.05


async def outcome(ctx, name, **args):
    return ToolOutcome(name=name, input=args, result=await run_tool(ctx, name, args))


async def test_player_stats_card(ctx):
    cards = build_cards(
        [await outcome(ctx, "get_player_stats", player_id=SAKA, venue="away")], THRESHOLD
    )

    (card,) = cards
    assert_matches(card, "Card")
    assert card["card_type"] == "stat"
    assert card["title"] == "Bukayo Saka — away, 2026/27"
    assert card["columns"] == ["Stat", "Total", "Per 90"]
    assert ["Goals", 1, 1.06] in card["rows"]
    assert card["source"] == {
        "source": "API-Football",
        "as_of": "2026-10-06T06:00:00Z",
        "is_stale": False,
    }


async def test_team_stats_card_has_form_strip(ctx):
    (card,) = build_cards([await outcome(ctx, "get_team_stats", team_id=BRE, last_n=3)], THRESHOLD)

    assert_matches(card, "Card")
    assert card["title"] == "Brentford — last 3, 2026/27"
    assert card["form"] == "LDL"
    assert ["Over 2.5 goals", "3/3 (100%)"] in card["rows"]


async def test_odds_card_lists_best_price_and_top_four(ctx):
    (card,) = build_cards([await outcome(ctx, "get_odds", fixture_id=201, market="h2h")], THRESHOLD)

    assert_matches(card, "Card")
    assert card["card_type"] == "odds"
    home = card["selections"][0]
    assert (home["label"], home["best_price"], home["best_bookmaker"]) == (
        "Aston Villa",
        2.25,
        "Coral",
    )
    assert home["prices"][0] == {"bookmaker": "Coral", "price": 2.25}
    assert all(len(s["prices"]) <= 4 for s in card["selections"])
    assert card["fixture"]["home"]["short_name"] == "AVL"


async def test_value_cards_one_per_selection_highlighted_above_threshold(ctx):
    cards = build_cards(
        [await outcome(ctx, "compare_to_market", fixture_id=201, market="h2h")], THRESHOLD
    )

    assert [c["selection"] for c in cards] == ["home", "draw", "away"]
    for card in cards:
        assert_matches(card, "Card")
        assert card["disclaimer"] == "Estimate, not advice."
        assert card["is_highlighted"] is (card["edge"] > THRESHOLD)


async def test_value_card_highlight_uses_the_threshold(ctx):
    result = await outcome(ctx, "compare_to_market", fixture_id=201, market="h2h")

    everything = build_cards([result], value_threshold=-1.0)
    nothing = build_cards([result], value_threshold=1.0)
    assert all(c["is_highlighted"] for c in everything)
    assert not any(c["is_highlighted"] for c in nothing)


async def test_failed_and_cardless_tools_make_no_cards(ctx):
    outcomes = [
        await outcome(ctx, "get_odds", fixture_id=201, market="btts"),
        await outcome(ctx, "resolve_entity", query="Spurs"),
        await outcome(ctx, "get_availability", fixture_id=201),
    ]
    assert build_cards(outcomes, THRESHOLD) == []


async def test_repeated_calls_make_one_card(ctx):
    same = await outcome(ctx, "get_odds", fixture_id=201, market="h2h")
    assert len(build_cards([same, same], THRESHOLD)) == 1


async def test_sources_are_unique_and_skip_reference_lookups(ctx):
    outcomes = [
        await outcome(ctx, "resolve_entity", query="Spurs"),
        await outcome(ctx, "get_odds", fixture_id=201, market="h2h"),
        await outcome(ctx, "get_odds", fixture_id=201, market="h2h"),
        await outcome(ctx, "get_team_stats", team_id=BRE),
        await outcome(ctx, "get_odds", fixture_id=201, market="btts"),
    ]

    assert collect_sources(outcomes) == [
        {"source": "The Odds API", "as_of": "2026-10-07T10:00:00Z", "is_stale": False},
        {"source": "API-Football", "as_of": "2026-10-06T06:00:00Z", "is_stale": False},
    ]


@pytest.mark.parametrize(
    ("selection", "line", "label"),
    [
        ("home", None, "Aston Villa"),
        ("draw", None, "Draw"),
        ("away", None, "Spurs"),
        ("over", 2.5, "Over 2.5"),
        ("under", 3.0, "Under 3"),
        ("yes", None, "Both teams to score"),
        ("no", None, "Not both teams to score"),
    ],
)
async def test_selection_labels(selection, line, label):
    fixture = {"home": {"name": "Aston Villa"}, "away": {"name": "Spurs"}}
    assert selection_label(fixture, selection, line) == label
