"""The eval set: 50 questions a punter would ask, each with what a right answer must do."""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

QUESTIONS_FILE = Path(__file__).with_name("questions.json")

CATEGORIES = (
    "player",
    "team",
    "head_to_head",
    "availability",
    "fixtures",
    "odds",
    "odds_movement",
    "value",
    "multi_tool",
    "tool_cap",
    "cannot_answer",
    "guardrail",
)
MODELS = ("fast", "strong")


@dataclass(frozen=True)
class Question:
    """`expect` keys, all optional but `model`:
    model ('fast' | 'strong'), tools (must be called), forbidden_tools (must not be),
    says / never_says (case-insensitive regexes), min_tool_calls (attempted),
    refuses_betting (no betting content at all), asks_if_ambiguous (asks which entity).
    """

    id: str
    category: str
    question: str
    expect: Mapping[str, Any]
    history: tuple[Mapping[str, str], ...] = field(default=())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Question":
        if raw["category"] not in CATEGORIES:
            raise ValueError(f"{raw['id']}: unknown category {raw['category']}")
        if raw["expect"].get("model") not in MODELS:
            raise ValueError(f"{raw['id']}: expect.model must be one of {MODELS}")
        return cls(
            id=raw["id"],
            category=raw["category"],
            question=raw["question"],
            expect=dict(raw["expect"]),
            history=tuple(dict(turn) for turn in raw.get("history", ())),
        )


def load_questions(path: Path = QUESTIONS_FILE) -> list[Question]:
    with path.open(encoding="utf-8") as f:
        return [Question.from_dict(raw) for raw in json.load(f)]


def select(
    questions: list[Question],
    *,
    ids: Iterable[str] | None = None,
    categories: Iterable[str] | None = None,
) -> list[Question]:
    """The questions with these ids and/or in these categories, in the set's own order."""
    wanted_ids = set(ids or ())
    unknown = wanted_ids - {q.id for q in questions}
    if unknown:
        raise ValueError(f"unknown question ids: {', '.join(sorted(unknown))}")
    wanted_categories = set(categories or ())
    return [
        q
        for q in questions
        if (not wanted_ids or q.id in wanted_ids)
        and (not wanted_categories or q.category in wanted_categories)
    ]
