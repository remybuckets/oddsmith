from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from orchestrator.model_client import (
    EFFORT,
    FALLBACK_BETA,
    AnthropicModel,
    TextDelta,
    Turn,
    TurnRequest,
    TurnUsage,
)

FINAL = SimpleNamespace(
    content=[SimpleNamespace(type="text", text="Hello there")],
    stop_reason="end_turn",
    usage=SimpleNamespace(
        input_tokens=12,
        output_tokens=5,
        cache_read_input_tokens=900,
        cache_creation_input_tokens=None,
    ),
)


class FakeStream:
    @property
    def text_stream(self):
        async def chunks():
            for chunk in ("Hello ", "there"):
                yield chunk

        return chunks()

    async def get_final_message(self):
        return FINAL


class FakeSdk:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @asynccontextmanager
    async def _stream(self, **kwargs):
        self.calls.append(kwargs)
        yield FakeStream()


def request(allow_tools=True):
    return TurnRequest(
        model="claude-sonnet-5-5",
        system=[{"type": "text", "text": "s"}],
        tools=[{"name": "t"}],
        messages=[{"role": "user", "content": "q"}],
        allow_tools=allow_tools,
    )


@pytest.mark.asyncio
async def test_streams_text_then_the_final_turn():
    items = [i async for i in AnthropicModel(FakeSdk()).stream_turn(request())]

    assert items[:2] == [TextDelta("Hello "), TextDelta("there")]
    assert items[2] == Turn(
        content=FINAL.content, stop_reason="end_turn", usage=TurnUsage(12, 5, 900, 0)
    )


@pytest.mark.asyncio
async def test_request_uses_fallbacks_caching_and_effort():
    sdk = FakeSdk()
    [i async for i in AnthropicModel(sdk).stream_turn(request())]

    (kwargs,) = sdk.calls
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["betas"] == [FALLBACK_BETA]
    assert kwargs["fallbacks"] == "default"
    assert kwargs["cache_control"] == {"type": "ephemeral"}
    assert kwargs["output_config"] == {"effort": EFFORT}
    assert kwargs["tool_choice"] == {"type": "auto"}


@pytest.mark.asyncio
async def test_no_more_tools_forces_an_answer():
    sdk = FakeSdk()
    [i async for i in AnthropicModel(sdk).stream_turn(request(allow_tools=False))]
    assert sdk.calls[0]["tool_choice"] == {"type": "none"}


def test_usage_adds_up():
    total = TurnUsage(1, 2, 3, 4) + TurnUsage(10, 20, 30, 40)
    assert total == TurnUsage(11, 22, 33, 44)
    assert total.total_input == 11 + 33 + 44
