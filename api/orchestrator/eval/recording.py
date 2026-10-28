"""Watches one answer being made: per-turn token usage, and the tool calls the loop refused.

The calls that ran are reported by the loop itself (AnswerDeps.on_tool_call) with their raw
results; what Claude is sent has been reworded for it (presentation.py)."""

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


def skipped_calls(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The tool calls Claude asked for after the answer had used its 8, which the loop
    refused, as {name, input, result, skipped}."""
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
        if json.loads(block["content"]) != LIMIT_RESULT:
            continue
        calls = [
            *calls,
            {
                "name": _field(use, "name"),
                "input": dict(_field(use, "input")),
                "result": LIMIT_RESULT,
                "skipped": True,
            },
        ]
    return calls
