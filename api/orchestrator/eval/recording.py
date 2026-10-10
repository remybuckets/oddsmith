"""Watches one answer being made: per-turn token usage and every tool call with its result."""

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from orchestrator.loop import LIMIT_RESULT
from orchestrator.model_client import ModelClient, TextDelta, Turn, TurnRequest, TurnUsage


class RecordingModel:
    """A ModelClient that passes turns through and keeps what was sent and what it cost."""

    def __init__(self, inner: ModelClient) -> None:
        self._inner = inner
        self.requests: list[TurnRequest] = []
        self.usages: list[TurnUsage] = []

    async def stream_turn(self, request: TurnRequest) -> AsyncIterator[TextDelta | Turn]:
        self.requests = [*self.requests, request]
        async for item in self._inner.stream_turn(request):
            if isinstance(item, Turn):
                self.usages = [*self.usages, item.usage]
            yield item

    @property
    def total_usage(self) -> TurnUsage:
        return sum(self.usages, TurnUsage())


def _field(block: Any, name: str) -> Any:
    return block[name] if isinstance(block, Mapping) else getattr(block, name)


def tool_calls(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every tool call in a conversation as {name, input, result, skipped}, in order.

    `skipped` marks calls the loop refused because the answer had used its 8 tool calls.
    """
    blocks = [
        block
        for message in messages
        if not isinstance(message["content"], str)
        for block in message["content"]
    ]
    uses = {_field(b, "id"): b for b in blocks if _field(b, "type") == "tool_use"}
    calls: list[dict[str, Any]] = []
    for block in blocks:
        if _field(block, "type") != "tool_result":
            continue
        use = uses[block["tool_use_id"]]
        result = json.loads(block["content"])
        calls = [
            *calls,
            {
                "name": _field(use, "name"),
                "input": dict(_field(use, "input")),
                "result": result,
                "skipped": result == LIMIT_RESULT,
            },
        ]
    return calls
