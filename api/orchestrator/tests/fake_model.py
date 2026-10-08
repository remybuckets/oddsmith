"""A scripted stand-in for Claude: replays turns and records every request it was sent."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from orchestrator.model_client import TextDelta, Turn, TurnRequest, TurnUsage

USAGE = TurnUsage(input_tokens=100, output_tokens=20, cache_read_tokens=1000, cache_write_tokens=0)


def tool_use(tool_id: str, name: str, **args: Any) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=args)


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


@dataclass(frozen=True)
class Scripted:
    """One model turn: text streamed in chunks, then the final content and stop reason."""

    chunks: tuple[str, ...] = ()
    tool_uses: tuple[SimpleNamespace, ...] = ()
    stop_reason: str | None = None

    def turn(self) -> Turn:
        text = [text_block("".join(self.chunks))] if self.chunks else []
        stop = self.stop_reason or ("tool_use" if self.tool_uses else "end_turn")
        return Turn(content=[*text, *self.tool_uses], stop_reason=stop, usage=USAGE)


@dataclass
class ScriptedModel:
    script: list[Scripted]
    requests: list[TurnRequest] = field(default_factory=list)
    error: Exception | None = None

    async def stream_turn(self, request: TurnRequest) -> AsyncIterator[TextDelta | Turn]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        scripted = self.script[min(len(self.requests), len(self.script)) - 1]
        for chunk in scripted.chunks:
            yield TextDelta(chunk)
        yield scripted.turn()
