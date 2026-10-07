"""/conversations and /conversations/{id}/messages."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints

from app import limits
from app.chat_stream import Turn, stream_answer
from app.clock import to_iso
from app.current_user import CurrentUserDep, DepsDep
from app.envelope import INVALID_INPUT_MESSAGE, ApiError, ErrorCode, not_found, ok
from app.gates import check_chat_gates
from app.repos import conversations, messages
from app.repos.conversations import Conversation, Cursor
from app.repos.messages import StoredMessage

router = APIRouter()

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_QUESTION_CHARS = 1000
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class Question(BaseModel):
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]


def _conversation_json(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "created_at": to_iso(conversation.created_at),
        "updated_at": to_iso(conversation.updated_at),
    }


def _message_json(message: StoredMessage) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "created_at": to_iso(message.created_at),
    }
    if message.role == "assistant":
        # Cards and sources aren't stored yet (no columns for them); see the lead-lane request.
        body |= {"cards": [], "sources": [], "feedback": message.feedback}
    return body


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/conversations")
async def list_conversations(
    user: CurrentUserDep,
    deps: DepsDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    try:
        after = Cursor.decode(cursor) if cursor else None
    except ValueError as exc:
        raise ApiError(422, ErrorCode.INVALID_INPUT, INVALID_INPUT_MESSAGE) from exc
    page, next_cursor = await conversations.list_page(deps.pool, user.id, limit, after)
    return ok(
        [_conversation_json(c) for c in page],
        meta={"next_cursor": next_cursor.encode() if next_cursor else None},
    )


@router.post("/conversations", status_code=201)
async def create_conversation(user: CurrentUserDep, deps: DepsDep) -> dict[str, Any]:
    return ok(_conversation_json(await conversations.create(deps.pool, user.id)))


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID, user: CurrentUserDep, deps: DepsDep
) -> dict[str, Any]:
    if not await conversations.is_owned_by(deps.pool, conversation_id, user.id):
        raise not_found()
    stored = await messages.list_for_conversation(deps.pool, conversation_id, user.id)
    return ok([_message_json(m) for m in stored])


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    question: Question,
    request: Request,
    user: CurrentUserDep,
    deps: DepsDep,
) -> StreamingResponse:
    now = deps.clock()
    await check_chat_gates(deps, user.id, user.profile, _client_ip(request), now)
    if not await conversations.is_owned_by(deps.pool, conversation_id, user.id):
        raise not_found()
    # Everything that can fail goes before the reservation, so a failure never costs a question.
    history = await messages.recent_history(deps.pool, conversation_id)
    used = await limits.reserve_question(
        deps.redis, user.id, now, deps.settings.daily_question_limit
    )
    turn = Turn(
        user_id=user.id,
        conversation_id=conversation_id,
        question=question.content,
        history=history,
        questions_used=used,
        asked_at=now,
    )
    return StreamingResponse(
        stream_answer(deps, turn), media_type="text/event-stream", headers=SSE_HEADERS
    )
