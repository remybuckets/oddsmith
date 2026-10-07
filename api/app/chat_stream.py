"""Turns orchestrator events into the SSE stream and saves the exchange when it completes."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sentry_sdk

from app import limits
from app.clock import uk_date
from app.deps import AppDeps
from app.envelope import error_payload, internal
from app.orchestrator_port import ChatTurn
from app.repos import messages
from app.repos.messages import Exchange, Usage

logger = logging.getLogger(__name__)

FORWARDED_EVENTS = frozenset({"tool_status", "text_delta", "card", "sources"})


@dataclass(frozen=True)
class Turn:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    question: str
    history: list[ChatTurn]
    questions_used: int
    asked_at: datetime


def sse_frame(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def _error_frame() -> str:
    return sse_frame({"type": "error", "error": error_payload(internal())})


async def _refund(deps: AppDeps, turn: Turn) -> None:
    try:
        await limits.refund_question(deps.redis, turn.user_id, turn.asked_at)
    except Exception:
        logger.exception("could not refund question for %s", turn.user_id)


async def _record_tokens(deps: AppDeps, turn: Turn, usage: Usage) -> None:
    """The answer is already saved, so a counter failure is logged, not shown to the user."""
    try:
        await limits.record_tokens(deps.redis, turn.asked_at, usage.total_tokens)
    except Exception:
        logger.exception("could not add %d tokens to the daily budget", usage.total_tokens)


@dataclass
class _Answer:
    """What one answer has produced so far. Local to a single request."""

    text_parts: list[str] = field(default_factory=list)
    usage: Usage | None = None
    sent_sources: bool = False
    failed: bool = False


async def _handle_event(deps: AppDeps, turn: Turn, event: dict[str, Any], answer: _Answer) -> str:
    """Updates the answer and returns the SSE frame to send, or '' to send nothing."""
    kind = event.get("type")
    if kind == "usage":
        # Count tokens on arrival: Claude has billed them whether or not the answer completes.
        answer.usage = Usage.from_event(event)
        await _record_tokens(deps, turn, answer.usage)
        return ""
    if kind == "error":
        logger.error("orchestrator error for %s: %s", turn.user_id, event.get("error"))
        answer.failed = True
        return ""
    if kind not in FORWARDED_EVENTS:
        logger.warning("dropped unknown orchestrator event type %r", kind)
        return ""
    if kind == "text_delta":
        answer.text_parts.append(event["text"])
    answer.sent_sources = answer.sent_sources or kind == "sources"
    return sse_frame(event)


def _exchange(turn: Turn, message_id: uuid.UUID, answer: _Answer) -> Exchange:
    if answer.usage is None:
        logger.error("orchestrator sent no usage event; recording zero tokens")
    return Exchange(
        conversation_id=turn.conversation_id,
        user_id=turn.user_id,
        assistant_message_id=message_id,
        question=turn.question,
        answer="".join(answer.text_parts),
        usage=answer.usage or Usage(),
        day=uk_date(turn.asked_at),
    )


async def stream_answer(deps: AppDeps, turn: Turn) -> AsyncIterator[str]:
    """message_start, forwarded events, sources, message_end — or an error event and a refund."""
    message_id = uuid.uuid4()
    yield sse_frame(
        {
            "type": "message_start",
            "message_id": str(message_id),
            "conversation_id": str(turn.conversation_id),
        }
    )
    answer = _Answer()
    try:
        async for event in deps.answer(turn.history, turn.question):
            frame = await _handle_event(deps, turn, event, answer)
            if answer.failed:
                break
            if frame:
                yield frame
        if not answer.failed:
            if not answer.sent_sources:
                yield sse_frame({"type": "sources", "sources": []})
            await messages.save_exchange(deps.pool, _exchange(turn, message_id, answer))
    except Exception as exc:
        logger.exception("answer failed for conversation %s", turn.conversation_id)
        sentry_sdk.capture_exception(exc)
        answer.failed = True
    if answer.failed:
        await _refund(deps, turn)
        yield _error_frame()
        return
    remaining = max(0, deps.settings.daily_question_limit - turn.questions_used)
    yield sse_frame(
        {"type": "message_end", "message_id": str(message_id), "questions_remaining": remaining}
    )
