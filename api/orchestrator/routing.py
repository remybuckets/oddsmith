"""Pick the model before the loop starts: switching mid-loop would lose the prompt cache."""

import re

# Value questions go to the stronger model (DECISIONS.md #3).
_VALUE_QUESTION = re.compile(
    r"\b(value|edge|over-?priced|under-?priced|mis-?priced|good bet|worth (a )?bet"
    r"|worth backing|fair (price|odds))\b",
    re.IGNORECASE,
)


def choose_model(question: str, *, fast: str, strong: str) -> str:
    return strong if _VALUE_QUESTION.search(question) else fast
