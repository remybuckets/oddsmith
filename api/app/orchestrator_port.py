"""The orchestrator interface from contracts/README.md, as the backend sees it."""

from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, TypedDict


class ChatTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


AnswerFn = Callable[[list[ChatTurn], str], AsyncIterator[dict[str, Any]]]
