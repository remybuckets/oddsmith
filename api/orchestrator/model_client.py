"""One streamed Claude turn behind a small interface, so the loop can be tested without Claude."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

MAX_TOKENS = 16000
EFFORT = "medium"  # multistep tool use; revisit with the eval set
# Server-side refusal fallback, routed by refusal category (no model list to maintain).
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class TurnUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: "TurnUsage") -> "TurnUsage":
        return TurnUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Turn:
    content: list[Any]  # SDK content blocks, sent back unchanged on the next request
    stop_reason: str | None
    usage: TurnUsage


@dataclass(frozen=True)
class TurnRequest:
    model: str
    system: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    allow_tools: bool


class ModelClient(Protocol):
    def stream_turn(self, request: TurnRequest) -> AsyncIterator[TextDelta | Turn]: ...


def _usage(usage: Any) -> TurnUsage:
    return TurnUsage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
    )


class AnthropicModel:
    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    async def stream_turn(self, request: TurnRequest) -> AsyncIterator[TextDelta | Turn]:
        async with self._client.beta.messages.stream(
            model=request.model,
            max_tokens=MAX_TOKENS,
            system=request.system,
            tools=request.tools,
            messages=request.messages,
            tool_choice={"type": "auto" if request.allow_tools else "none"},
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},  # caches the growing loop history too
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            async for text in stream.text_stream:
                yield TextDelta(text)
            message = await stream.get_final_message()
        yield Turn(
            content=list(message.content),
            stop_reason=message.stop_reason,
            usage=_usage(message.usage),
        )
