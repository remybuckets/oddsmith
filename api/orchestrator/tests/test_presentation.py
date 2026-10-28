"""Regression tests for the day-7 eval: answers showed UTC times as UK times and cited the
wrong as-of time, because Claude was left to convert timestamps by hand."""

import copy
from datetime import UTC, datetime

from orchestrator.presentation import present

NOW = datetime(2026, 10, 10, 19, 30, tzinfo=UTC)

ODDS = {
    "ok": True,
    "source": "The Odds API",
    "as_of": "2026-10-10T17:30:59Z",
    "is_stale": False,
    "freshness_limit_hours": 6,
    "warnings": [],
    "data": {
        "fixture": {"fixture_id": 63, "kickoff_at": "2026-10-17T14:00:00Z"},
        "selections": [
            {
                "selection": "home",
                "best_price": 1.25,
                "prices": [{"bookmaker": "888sport", "captured_at": "2026-10-10T17:30:59Z"}],
            }
        ],
    },
}


def test_every_timestamp_is_shown_in_uk_time():
    shown = present(ODDS, NOW)

    assert shown["data"]["fixture"]["kickoff_at"] == "Sat 17 Oct 2026, 15:00"  # BST
    assert shown["data"]["selections"][0]["prices"][0]["captured_at"] == "Sat 10 Oct 2026, 18:30"
    assert shown["as_of"] == "Sat 10 Oct 2026, 18:30"


def test_winter_timestamps_are_not_shifted():
    after_clocks_go_back = {**ODDS, "data": {"kickoff_at": "2026-10-31T17:30:00Z"}}

    assert present(after_clocks_go_back, NOW)["data"]["kickoff_at"] == "Sat 31 Oct 2026, 17:30"


def test_the_citation_is_ready_made_with_the_as_of_time():
    assert present(ODDS, NOW)["cite_as"] == "(The Odds API, 10 Oct 18:30)"


def test_the_value_model_is_cited_by_its_short_name():
    model = {**ODDS, "source": "Oddsmith model (API-Football xG, The Odds API prices)"}

    assert present(model, NOW)["cite_as"] == "(Oddsmith model, 10 Oct 18:30)"


def test_the_age_of_the_data_is_worked_out_for_claude():
    assert present(ODDS, NOW)["age"] == "1 hour 59 minutes"
    assert present({**ODDS, "as_of": "2026-10-09T18:00:00Z"}, NOW)["age"] == "1 day 1 hour"
    assert present({**ODDS, "as_of": "2026-10-10T19:10:00Z"}, NOW)["age"] == "20 minutes"


def test_lookups_carry_no_as_of_to_cite():
    lookup = {**ODDS, "source": "API-Football", "freshness_limit_hours": None}

    shown = present(lookup, NOW)

    assert "cite_as" not in shown
    assert "as_of" not in shown
    assert "age" not in shown


def test_dates_numbers_and_other_text_are_left_alone():
    result = {
        **ODDS,
        "data": {"expected_return": "2026-10-25", "price": 2.5, "name": "888sport", "n": None},
    }

    assert present(result, NOW)["data"] == result["data"]


def test_errors_pass_through_unchanged():
    error = {"ok": False, "error": {"code": "no_data", "message": "No prices."}}

    assert present(error, NOW) == error


def test_the_tool_result_itself_is_not_changed():
    before = copy.deepcopy(ODDS)

    present(ODDS, NOW)

    assert before == ODDS
