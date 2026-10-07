"""/feedback: thumbs up or down on an answer."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.current_user import CurrentUserDep, DepsDep
from app.envelope import not_found, ok
from app.repos import feedback

router = APIRouter()

MAX_NOTE_CHARS = 1000


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    rating: Literal[1, -1]
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)


@router.post("/feedback")
async def post_feedback(
    body: FeedbackRequest, user: CurrentUserDep, deps: DepsDep
) -> dict[str, Any]:
    saved = await feedback.upsert(deps.pool, user.id, body.message_id, body.rating, body.note)
    if not saved:
        raise not_found()
    return ok()
