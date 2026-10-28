import re
from collections import Counter

import pytest

from orchestrator.eval.questions import CATEGORIES, Question, load_questions, select
from orchestrator.routing import choose_model
from orchestrator.tools import RUNNERS

QUESTIONS = load_questions()


def test_there_are_fifty_questions_with_unique_ids():
    assert len(QUESTIONS) == 50
    assert len({q.id for q in QUESTIONS}) == 50
    assert len({q.question for q in QUESTIONS}) == 50


def test_every_category_is_covered():
    counts = Counter(q.category for q in QUESTIONS)

    assert set(counts) == set(CATEGORIES)
    assert counts["value"] >= 4
    assert counts["tool_cap"] >= 3
    assert counts["cannot_answer"] >= 3
    assert counts["guardrail"] >= 5


def test_every_beta_tool_is_expected_by_some_question():
    expected = {tool for q in QUESTIONS for tool in q.expect.get("tools", [])}

    assert expected == set(RUNNERS)


def test_expected_tools_and_patterns_are_valid():
    for question in QUESTIONS:
        for tool in (
            *question.expect.get("tools", []),
            *question.expect.get("forbidden_tools", []),
        ):
            assert tool in RUNNERS, f"{question.id}: unknown tool {tool}"
        for pattern in (*question.expect.get("says", []), *question.expect.get("never_says", [])):
            re.compile(pattern)


def test_expected_model_matches_the_router():
    for question in QUESTIONS:
        routed = choose_model(question.question, fast="fast", strong="strong")
        assert question.expect["model"] == routed, question.id


def test_the_data_cannot_answer_questions_cover_the_known_gaps():
    gaps = " ".join(q.question for q in QUESTIONS if q.category == "cannot_answer")

    assert "xG" in gaps  # player xG is never provided (DECISIONS.md #7)
    assert "press conference" in gaps  # news is off (DECISIONS.md #5)
    assert "Barcelona" in gaps  # a fixture that doesn't exist


def test_history_is_well_formed():
    with_history = [q for q in QUESTIONS if q.history]

    assert with_history
    for question in with_history:
        assert question.history[0]["role"] == "user"
        assert all(turn["content"] for turn in question.history)


def test_select_filters_by_id_and_category():
    assert [q.id for q in select(QUESTIONS, ids=["v01", "p01"])] == ["p01", "v01"]
    assert {q.category for q in select(QUESTIONS, categories=["value"])} == {"value"}
    assert select(QUESTIONS) == QUESTIONS


def test_select_rejects_an_unknown_id():
    with pytest.raises(ValueError, match="zz9"):
        select(QUESTIONS, ids=["zz9"])


def test_a_question_needs_an_expected_model():
    with pytest.raises(ValueError, match="model"):
        Question.from_dict({"id": "q", "category": "team", "question": "?", "expect": {}})
