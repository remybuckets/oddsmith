from datetime import UTC, datetime

import pytest

from orchestrator.eval.figures import classify, evidence_from, extract

NOW = datetime(2026, 10, 10, 19, 0, tzinfo=UTC)

ODDS_CALL = {
    "name": "get_odds",
    "input": {"fixture_id": 59, "market": "h2h"},
    "result": {
        "ok": True,
        "source": "The Odds API",
        "as_of": "2026-10-10T17:30:59Z",
        "is_stale": False,
        "freshness_limit_hours": 6,
        "warnings": [],
        "data": {
            "fixture": {
                "fixture_id": 59,
                "matchweek": 6,
                "kickoff_at": "2026-10-11T15:30:00Z",
                "status": "scheduled",
                "home": {"id": 5, "name": "Liverpool", "short_name": "Liverpool"},
                "away": {"id": 10, "name": "Manchester City", "short_name": "Man City"},
                "home_score": None,
                "away_score": None,
            },
            "market": "h2h",
            "line": None,
            "selections": [
                {
                    "selection": "home",
                    "best_price": 2.45,
                    "best_bookmaker": "888sport",
                    "implied_probability": 0.4082,
                    "prices": [
                        {
                            "bookmaker": "888sport",
                            "price": 2.45,
                            "captured_at": "2026-10-10T17:30:59Z",
                        },
                        {"bookmaker": "Coral", "price": 2.4, "captured_at": "2026-10-10T17:30:59Z"},
                    ],
                }
            ],
            "overround": 1.0432,
        },
    },
}
STATS_CALL = {
    "name": "get_team_stats",
    "input": {"team_id": 5, "last_n": 5},
    "result": {
        "ok": True,
        "source": "API-Football",
        "as_of": "2026-10-10T12:01:08Z",
        "is_stale": False,
        "freshness_limit_hours": 48,
        "warnings": [],
        "data": {
            "team": {"id": 5, "name": "Liverpool"},
            "played": 5,
            "won": 3,
            "goals_for": 11,
            "goals_against": 4,
            "xg_for": 9.37,
            "over_2_5": {"count": 4, "of": 5, "pct": 80.0},
            "matches": [],
        },
    },
}


def evidence(*calls, question="Best price on Liverpool v City?"):
    return evidence_from(list(calls), question=question, now=NOW)


def verdicts(text, *calls, **kwargs):
    figures, _ = extract(text)
    found = evidence(*calls, **kwargs)
    return {f.raw: classify(f, found).kind for f in figures}


def test_numbers_are_extracted_with_their_precision():
    figures, _ = extract("Liverpool are 2.45 with 888sport, a 40.8% chance; 3rd in the table.")

    assert [(f.raw, f.value, f.decimals) for f in figures] == [
        ("2.45", 2.45, 2),
        ("40.8%", 40.8, 1),
        ("3rd", 3.0, 0),
    ]


def test_dates_times_seasons_and_the_helpline_are_not_treated_as_figures():
    text = (
        "Kick-off is Sunday 11 October at 16:30 (The Odds API, 10 Oct 18:30). In 2026/27 "
        "they're unbeaten. GamCare: 0808 8020 133."
    )

    figures, moments = extract(text)

    assert figures == []
    assert [(m.kind, m.value) for m in moments] == [
        ("date", (11, 10)),
        ("date", (10, 10)),
        ("time", (16, 30)),
        ("time", (18, 30)),
    ]


def test_twelve_hour_times_are_read():
    _, moments = extract("It's a 4.30pm kick-off, or 3pm for the others.")

    assert [m.value for m in moments if m.kind == "time"] == [(16, 30), (15, 0)]


def test_figures_from_tool_results_are_exact():
    text = "Best price 2.45 (888sport), implied 40.8%. 11 scored, 4 conceded, xG 9.4, over 80%."

    assert verdicts(text, ODDS_CALL, STATS_CALL) == {
        "2.45": "exact",
        "40.8%": "exact",
        "11": "exact",
        "4": "exact",
        "9.4": "exact",
        "80%": "exact",
    }


def test_an_invented_figure_is_unexplained():
    assert verdicts("They're 3.75 to win and have 137 points.", ODDS_CALL, STATS_CALL) == {
        "3.75": "unexplained",
        "137": "unexplained",
    }


def test_ids_do_not_ground_figures():
    assert verdicts("They have 77 points.", ODDS_CALL) == {"77": "unexplained"}


def test_simple_arithmetic_on_tool_figures_is_derived():
    text = "Goal difference of 7, 2.2 scored a game, and Coral's 2.40 implies 41.7%."

    assert verdicts(text, ODDS_CALL, STATS_CALL) == {
        "7": "derived",
        "2.2": "derived",
        "2.40": "exact",
        "41.7%": "derived",
    }


def test_numbers_the_user_gave_are_grounded():
    assert verdicts("Over 2.5 landed in 4 of the last 5.", STATS_CALL, question="Over 2.5?") == {
        "2.5": "exact",
        "4": "exact",
        "5": "exact",
    }


def test_data_age_is_grounded_from_as_of():
    # as_of 17:30:59 UTC, now 19:00 UTC: about an hour and a half old.
    assert verdicts("Prices are about 89 minutes old.", ODDS_CALL) == {"89": "exact"}


def test_data_age_only_grounds_durations():
    assert verdicts("They have 89 points.", ODDS_CALL) == {"89": "unexplained"}


def test_figure_sources_are_reported():
    figures, _ = extract("Best price 2.45.")

    verdict = classify(figures[0], evidence(ODDS_CALL, STATS_CALL))

    assert verdict.sources == frozenset({"The Odds API"})


def test_moments_are_checked_against_uk_times_in_the_results():
    found = evidence(ODDS_CALL)

    assert (16, 30) in found.times  # kick-off 15:30 UTC is 16:30 BST
    assert (18, 30) in found.times  # as_of 17:30:59 UTC
    assert (15, 30) not in found.times
    assert (11, 10) in found.dates
    assert (10, 10) in found.dates


@pytest.mark.parametrize("text", ["888sport", "1X2", "U21s"])
def test_numbers_inside_words_are_ignored(text):
    figures, _ = extract(f"Check {text} for this.")

    assert figures == []


def test_helpline_hours_and_the_goals_line_are_not_data_figures():
    figures, _ = extract("GamCare is open 24/7. Over 2.5 landed.")

    assert [f.raw for f in figures] == ["2.5"]
    assert verdicts("Over 2.5 landed.", STATS_CALL, question="Goals?") == {"2.5": "exact"}


def test_a_fair_price_from_a_model_probability_is_derived():
    # implied_probability 0.4082 -> 1 / 0.4082 = 2.45 is exact here, so use the overround.
    assert verdicts("Fair price about 0.96.", ODDS_CALL) == {"0.96": "derived"}
