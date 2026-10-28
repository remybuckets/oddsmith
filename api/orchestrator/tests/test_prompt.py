from datetime import UTC, datetime

import pytest

from orchestrator.prompt import (
    MAX_HISTORY_TURNS,
    SYSTEM_PROMPT,
    history_messages,
    question_message,
    system_blocks,
)
from orchestrator.routing import choose_model

FAST, STRONG = "claude-sonnet-5-5", "claude-opus-5-5"


def test_system_prompt_carries_the_spec_rules():
    for rule in (
        "resolve_entity",
        "GamCare (0808 8020 133)",
        "GAMSTOP",
        "estimate",
        "never say lock",
        "Premier League 2026/27",
    ):
        assert rule.lower() in SYSTEM_PROMPT.lower()


def test_system_prompt_is_cached_and_stable():
    blocks = system_blocks()

    assert blocks == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    assert "{" not in SYSTEM_PROMPT  # no per-request values that would break the cache


def test_question_carries_the_date_and_time_in_uk_time():
    # Eval regression: with the date but no time, Claude took matches that had finished
    # that afternoon for matches still to come, and recomputed stats without them.
    late_evening_utc = datetime(2026, 10, 9, 23, 30, tzinfo=UTC)  # already Saturday in London

    message = question_message("Who's injured for Villa?", late_evening_utc)

    assert message["role"] == "user"
    assert message["content"] == (
        "It is Saturday 10 October 2026, 00:30 UK time.\n\nWho's injured for Villa?"
    )


def test_question_using_banned_words_carries_a_reminder_not_to_repeat_them():
    # Eval regression (g01, g06, two runs): with the ban only in the system prompt, Claude
    # still echoed the user's "banker" and "guaranteed" while turning them down.
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

    content = question_message("Are City a lock? Surely that's guaranteed. A LOCK.", now)["content"]

    assert content.startswith(
        "It is Wednesday 28 October 2026, 12:00 UK time.\n\n"
        "Are City a lock? Surely that's guaranteed. A LOCK."
    )
    assert content.endswith(
        '\n\n(Don\'t use the words "lock" or "guaranteed" in your answer, not even to deny '
        'or quote them. Say "no bet is certain" instead.)'
    )


def test_history_keeps_recent_turns_and_starts_with_the_user():
    history = [{"role": "assistant", "content": "orphan"}] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(MAX_HISTORY_TURNS + 6)
    ]

    messages = history_messages(history)

    assert len(messages) <= MAX_HISTORY_TURNS
    assert messages[0]["role"] == "user"
    assert messages[-1] == {"role": "assistant", "content": f"turn {MAX_HISTORY_TURNS + 5}"}


def test_history_drops_empty_turns():
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": ""}]
    assert history_messages(history) == [{"role": "user", "content": "hi"}]


@pytest.mark.parametrize(
    "question",
    [
        "Is there value in Newcastle to win?",
        "What's the edge on over 2.5 at Brentford?",
        "Are Spurs overpriced this weekend?",
        "is Arsenal at 1.40 a good bet",
        "What's a fair price for the draw?",
    ],
)
def test_value_questions_use_the_strong_model(question):
    assert choose_model(question, fast=FAST, strong=STRONG) == STRONG


@pytest.mark.parametrize(
    "question",
    [
        "How has Saka done away from home this season?",
        "Who's injured for Villa vs Spurs?",
        "What's the best price on Haaland to score Saturday?",
        "Which players get booked most in this fixture?",
        "Valuable players at Villa?",
    ],
)
def test_other_questions_use_the_fast_model(question):
    assert choose_model(question, fast=FAST, strong=STRONG) == FAST
