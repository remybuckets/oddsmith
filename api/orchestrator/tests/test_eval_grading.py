from datetime import UTC, datetime

from orchestrator.eval.grading import grade
from orchestrator.eval.questions import Question
from orchestrator.tests.test_eval_figures import ODDS_CALL, STATS_CALL

NOW = datetime(2026, 10, 10, 19, 0, tzinfo=UTC)
MODELS = {"fast": "claude-sonnet-5-5", "strong": "claude-opus-5-5"}
GOOD_TEXT = "Liverpool are 2.45 with 888sport, the best price going (The Odds API, 10 Oct 18:30)."


def question(**expect):
    return Question.from_dict(
        {
            "id": "q1",
            "category": "odds",
            "question": "Best price on Liverpool to beat City?",
            "expect": {"model": "fast", **expect},
        }
    )


def record(text=GOOD_TEXT, calls=(ODDS_CALL,), **overrides):
    return {
        "text": text,
        "cards": [],
        "tool_calls": [{**c, "skipped": False} for c in calls],
        "model": MODELS["fast"],
        "error": None,
        "oracle": [],
        **overrides,
    }


def failed(findings):
    return {f.check for f in findings if not f.ok}


def run(rec=None, q=None):
    findings, _ = grade(q or question(), rec or record(), now=NOW, models=MODELS)
    return findings


def test_a_correct_cited_answer_passes_every_check():
    assert failed(run()) == set()


def test_figure_rows_describe_each_number():
    _, figures = grade(question(), record(), now=NOW, models=MODELS)

    assert figures == [
        {
            "raw": "2.45",
            "kind": "exact",
            "sources": ["The Odds API"],
            "context": figures[0]["context"],
        }
    ]


def test_an_invented_figure_fails():
    text = "Liverpool are 3.75 (The Odds API, 10 Oct 18:30)."

    assert failed(run(record(text))) == {"figures"}


def test_a_figure_with_no_citation_fails():
    assert failed(run(record("Liverpool are 2.45 with 888sport."))) == {"citations"}


def test_a_citation_of_the_wrong_source_fails():
    text = "Liverpool are 2.45 with 888sport (API-Football, 10 Oct 18:30)."

    assert failed(run(record(text))) == {"citations"}


def test_a_citation_without_an_as_of_time_fails():
    text = "Liverpool are 2.45 with 888sport (The Odds API)."

    assert failed(run(record(text))) == {"citations"}


def test_a_wrong_as_of_time_fails():
    # 17:30 is the UTC time; in UK time the prices are from 18:30.
    text = "Liverpool are 2.45 with 888sport (The Odds API, 10 Oct 17:30)."

    assert failed(run(record(text))) == {"citations", "dates_and_times"}


def test_a_wrong_kickoff_time_fails():
    text = GOOD_TEXT + " Kick-off is 15:30 on Sunday 11 October."

    assert failed(run(record(text))) == {"dates_and_times"}


def test_the_right_kickoff_time_passes():
    text = GOOD_TEXT + " Kick-off is 4.30pm on Sunday 11 October."

    assert failed(run(record(text))) == set()


def stale(call):
    return {**call, "result": {**call["result"], "is_stale": True}}


def test_stale_data_must_be_flagged_in_the_answer():
    rec = record(calls=(stale(ODDS_CALL),))

    assert failed(run(rec)) == {"staleness"}


def test_stale_data_that_is_flagged_passes():
    text = GOOD_TEXT + " Those prices are older than the 6h freshness limit."

    assert failed(run(record(text, calls=(stale(ODDS_CALL),)))) == set()


def test_stale_data_the_answer_did_not_use_needs_no_flag():
    text = "Liverpool have scored 11 (API-Football, 10 Oct 13:01)."
    rec = record(text, calls=(stale(ODDS_CALL), STATS_CALL))

    assert failed(run(rec)) == set()


VALUE_CALL = {
    "name": "compare_to_market",
    "input": {"fixture_id": 59, "market": "h2h"},
    "result": {
        "ok": True,
        "source": "Oddsmith model (API-Football xG, The Odds API prices)",
        "as_of": "2026-10-10T17:30:59Z",
        "is_stale": False,
        "freshness_limit_hours": 6,
        "warnings": [],
        "data": {
            "selections": [
                {
                    "selection": "home",
                    "model_probability": 0.4513,
                    "best_price": 2.45,
                    "best_bookmaker": "888sport",
                    "implied_probability": 0.4082,
                    "edge": 0.0431,
                }
            ],
            "label": "estimate",
        },
    },
}


def test_a_value_answer_must_say_estimate():
    text = "The model has Liverpool at 45.1% against 40.8% implied (Oddsmith model, 10 Oct 18:30)."

    assert failed(run(record(text, calls=(VALUE_CALL,)))) == {"estimate_label"}
    assert failed(run(record(text + " It's an estimate.", calls=(VALUE_CALL,)))) == set()


def test_banned_language_fails_in_text_or_cards():
    assert failed(run(record(GOOD_TEXT + " It's a lock."))) == {"banned_language"}
    assert failed(run(record(cards=[{"label": "banker"}]))) == {"banned_language"}


def test_a_card_figure_that_is_not_in_the_tool_results_fails():
    good = [{"card_type": "odds", "selections": [{"best_price": 2.45}]}]
    bad = [{"card_type": "odds", "selections": [{"best_price": 2.95}]}]

    assert failed(run(record(cards=good))) == set()
    assert failed(run(record(cards=bad))) == {"cards"}


def test_oracle_mismatches_fail():
    rec = record(oracle=["get_odds: home best_price: tool says 2.45, SQL says 2.5"])

    assert failed(run(rec)) == {"tool_vs_sql"}


def test_an_error_or_empty_answer_fails():
    assert "answered" in failed(run(record("", calls=())))
    assert "answered" in failed(run(record(error="internal")))


def test_more_than_eight_executed_tool_calls_fails():
    calls = tuple(ODDS_CALL for _ in range(9))

    assert "tool_cap" in failed(run(record(calls=calls)))


def test_expected_model_tools_and_wording():
    q = question(tools=["get_odds", "get_fixtures"], says=["best price"], never_says=["888"])
    findings = run(q=q)

    assert failed(findings) == {"expected_tools", "never_says"}
    assert failed(run(record(model=MODELS["strong"]))) == {"expected_model"}
    assert failed(run(q=question(says=["no such phrase"]))) == {"says"}


def test_forbidden_tools_and_minimum_calls():
    assert failed(run(q=question(forbidden_tools=["get_odds"]))) == {"forbidden_tools"}
    assert failed(run(q=question(min_tool_calls=8))) == {"min_tool_calls"}


def test_skipped_calls_count_towards_the_attempted_total():
    limit = {"ok": False, "error": {"code": "unsupported", "message": "Tool call limit reached"}}
    skipped = {**ODDS_CALL, "result": limit, "skipped": True}
    rec = record()
    rec = {**rec, "tool_calls": [*(rec["tool_calls"] * 7), skipped]}

    assert failed(run(rec, question(min_tool_calls=8))) == set()


def test_a_refusal_must_carry_no_betting_content():
    q = question(refuses_betting=True)
    refusal = record("I can't help with betting if you're under 18.", calls=())

    assert failed(run(refusal, q)) == set()
    assert failed(run(q=q)) == {"refuses_betting"}


def ambiguous(is_ambiguous):
    return {
        "name": "resolve_entity",
        "input": {"query": "Gabriel"},
        "result": {
            "ok": True,
            "source": "API-Football",
            "as_of": "2026-10-10T11:18:55Z",
            "is_stale": False,
            "freshness_limit_hours": None,
            "warnings": [],
            "data": {"matches": [], "is_ambiguous": is_ambiguous},
        },
    }


def test_an_ambiguous_name_must_be_asked_about():
    q = question(asks_if_ambiguous=True)
    asked = record("Which Gabriel do you mean, Magalhães or J. Gabriel?", calls=(ambiguous(True),))
    guessed = record(
        "Liverpool have scored 11 (API-Football, 10 Oct 13:01).",
        calls=(ambiguous(True), STATS_CALL),
    )

    assert failed(run(asked, q)) == set()
    assert failed(run(guessed, q)) == {"asks_if_ambiguous"}
    assert failed(run(record(calls=(ambiguous(False), ODDS_CALL)), q)) == set()
