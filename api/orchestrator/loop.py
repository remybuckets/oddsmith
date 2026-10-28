"""The Claude tool-use loop behind answer(): events in the order contracts/README.md sets."""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from orchestrator.cards import ToolOutcome, build_cards, collect_sources
from orchestrator.config import OrchestratorSettings
from orchestrator.model_client import ModelClient, Turn, TurnRequest, TurnUsage
from orchestrator.presentation import present
from orchestrator.prompt import history_messages, question_message, system_blocks
from orchestrator.routing import choose_model
from orchestrator.tools import run_tool, tool_definitions
from orchestrator.tools.context import ToolContext

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
MAX_TURNS = MAX_TOOL_CALLS + 2  # every turn but the last runs at least one tool

TURN_BREAK = "\n\n"  # between text from separate model turns
NOTE_LIMIT = 200  # characters: shorter text before more tool calls is a note, not the answer

ERROR_MESSAGE = "Oddsmith couldn't finish that answer. Please try again."
REFUSAL_TEXT = "Sorry, I can't help with that one. Ask me about Premier League stats or odds."
LIMIT_RESULT = {
    "ok": False,
    "error": {
        "code": "unsupported",
        "message": ("Tool call limit reached for this answer. Answer with what you already have."),
    },
}

TOOL_LABELS = {
    "resolve_entity": "Looking that up",
    "get_player_stats": "Checking player stats",
    "get_team_stats": "Checking team stats",
    "get_head_to_head": "Checking past meetings",
    "get_fixtures": "Checking fixtures",
    "get_league_table": "Checking the table",
    "get_availability": "Checking injuries",
    "search_news": "Checking team news",
    "get_odds": "Checking odds",
    "get_odds_movement": "Checking price moves",
    "compare_to_market": "Comparing with the market",
}


@dataclass(frozen=True)
class AnswerDeps:
    model: ModelClient
    connection: Callable[[], AbstractAsyncContextManager[asyncpg.Connection]]
    settings: OrchestratorSettings
    clock: Callable[[], datetime]
    on_tool_call: Callable[[ToolOutcome], None] | None = None  # sees each raw tool result


@dataclass(frozen=True)
class ToolCall:
    outcome: ToolOutcome
    duration_ms: int

    def record(self) -> dict[str, Any]:
        result = self.outcome.result
        return {
            "tool": self.outcome.name,
            "input": self.outcome.input,
            "source": result.get("source"),
            "as_of": result.get("as_of"),
            "is_stale": result.get("is_stale"),
            "duration_ms": self.duration_ms,
            "error": None if result["ok"] else result["error"]["message"],
        }


@dataclass(frozen=True)
class ToolRound:
    calls: list[ToolCall]
    results: list[dict[str, Any]]  # tool_result blocks, one per tool_use


def _text(text: str) -> dict[str, Any]:
    return {"type": "text_delta", "text": text}


def _status(tool: str, status: str) -> dict[str, Any]:
    return {
        "type": "tool_status",
        "tool": tool,
        "status": status,
        "label": TOOL_LABELS.get(tool, "Checking the data"),
    }


def _tool_result(tool_use_id: str, result: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The result as Claude reads it: UK times and a ready-made citation (presentation.py)."""
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(present(result, now)),
        "is_error": not result["ok"],
    }


@dataclass(frozen=True)
class _TurnEnd:
    turn: Turn
    held: tuple[str, ...]  # text not streamed: before the first tool results, or a short note
    speaking: bool  # some of this turn's text was streamed


async def _speak(
    deps: AnswerDeps, request: TurnRequest, *, live: bool, after_text: bool
) -> AsyncIterator[dict[str, Any] | _TurnEnd]:
    """Streams a turn's text once the first tool results are back and the text is long enough
    to be the answer; a short note followed by more tool calls (eval run 7: "Fixtures 81, 89,
    90.") stays held and is dropped. Ends with the finished turn."""
    held: tuple[str, ...] = ()
    speaking = False
    async for item in deps.model.stream_turn(request):
        if isinstance(item, Turn):
            yield _TurnEnd(item, held, speaking)
            return
        held = (*held, item.text)
        if not live or (not speaking and sum(map(len, held)) < NOTE_LIMIT):
            continue
        if after_text and not speaking:
            yield _text(TURN_BREAK)
        speaking = True
        for text in held:
            yield _text(text)
        held = ()


async def _run_tools(
    deps: AnswerDeps, tool_uses: list[Any], now: datetime, budget: int
) -> AsyncIterator[dict[str, Any] | ToolRound]:
    """Runs up to `budget` tool calls, yielding status events, then the ToolRound."""
    calls: list[ToolCall] = []
    results: list[dict[str, Any]] = []
    async with deps.connection() as conn:
        ctx = ToolContext(conn=conn, now=now)
        for block in tool_uses:
            if len(calls) >= budget:
                results = [*results, _tool_result(block.id, LIMIT_RESULT, now)]
                continue
            yield _status(block.name, "started")
            started = time.perf_counter()
            result = await run_tool(ctx, block.name, dict(block.input))
            duration_ms = round((time.perf_counter() - started) * 1000)
            yield _status(block.name, "finished" if result["ok"] else "failed")
            outcome = ToolOutcome(block.name, dict(block.input), result)
            if deps.on_tool_call is not None:
                deps.on_tool_call(outcome)
            calls = [*calls, ToolCall(outcome, duration_ms)]
            results = [*results, _tool_result(block.id, result, now)]
    yield ToolRound(calls=calls, results=results)


def _closing_events(model: str, usage: TurnUsage, calls: list[ToolCall], threshold: float):
    outcomes = [c.outcome for c in calls]
    cards = [{"type": "card", "card": card} for card in build_cards(outcomes, threshold)]
    logger.info(
        "answer model=%s tokens_in=%d tokens_out=%d cache_read=%d cache_write=%d tool_calls=%d",
        model,
        usage.total_input,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        len(calls),
    )
    return [
        *cards,
        {"type": "sources", "sources": collect_sources(outcomes)},
        {
            "type": "usage",
            "model": model,
            "tokens_in": usage.total_input,
            "tokens_out": usage.output_tokens,
            "tool_calls": [c.record() for c in calls],
        },
    ]


async def _answer(
    deps: AnswerDeps, history: list[dict[str, str]], question: str
) -> AsyncIterator[dict[str, Any]]:
    settings, now = deps.settings, deps.clock()
    model = choose_model(question, fast=settings.model_fast, strong=settings.model_strong)
    tools = tool_definitions(news_enabled=settings.news_enabled)
    messages = [*history_messages(history), question_message(question, now)]
    calls: list[ToolCall] = []
    usage = TurnUsage()
    live = False  # text streams once the first tool results are back
    spoken = False  # an earlier turn's text has been streamed

    for _ in range(MAX_TURNS):
        request = TurnRequest(
            model, system_blocks(), tools, messages, allow_tools=len(calls) < MAX_TOOL_CALLS
        )
        async for item in _speak(deps, request, live=live, after_text=spoken):
            if isinstance(item, _TurnEnd):
                end = item
            else:
                yield item
        turn = end.turn
        usage = usage + turn.usage
        tool_uses = [b for b in turn.content if b.type == "tool_use"]
        if turn.stop_reason != "tool_use" or not tool_uses:
            if end.held and spoken and not end.speaking:
                yield _text(TURN_BREAK)
            for text in end.held:
                yield _text(text)
            if turn.stop_reason == "refusal":
                yield _text(REFUSAL_TEXT)
            elif turn.stop_reason == "max_tokens":
                logger.warning("answer hit max_tokens with model %s", model)
            break
        async for item in _run_tools(deps, tool_uses, now, MAX_TOOL_CALLS - len(calls)):
            if isinstance(item, ToolRound):
                calls = [*calls, *item.calls]
                messages = [
                    *messages,
                    {"role": "assistant", "content": turn.content},
                    {"role": "user", "content": item.results},
                ]
            else:
                yield item
        spoken = spoken or end.speaking
        live = True

    for event in _closing_events(model, usage, calls, settings.value_edge_threshold):
        yield event


async def run_answer(
    deps: AnswerDeps, history: list[dict[str, str]], question: str
) -> AsyncIterator[dict[str, Any]]:
    """answer() with its dependencies passed in. On failure: one error event, then stop."""
    try:
        async for event in _answer(deps, history, question):
            yield event
    except Exception:
        logger.exception("answer failed")
        yield {"type": "error", "error": {"code": "internal", "message": ERROR_MESSAGE}}
