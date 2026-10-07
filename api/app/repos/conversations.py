"""conversations: a user's chats, newest first, with keyset pagination."""

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_COLUMNS = "id, title, created_at, updated_at"


@dataclass(frozen=True)
class Conversation:
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Cursor:
    updated_at: datetime
    id: uuid.UUID

    def encode(self) -> str:
        raw = json.dumps([self.updated_at.isoformat(), str(self.id)]).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def decode(token: str) -> "Cursor":
        """Raises ValueError for anything that isn't a cursor this module produced."""
        try:
            updated_at, conversation_id = json.loads(base64.urlsafe_b64decode(token.encode()))
            return Cursor(datetime.fromisoformat(updated_at), uuid.UUID(conversation_id))
        except (binascii.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("invalid cursor") from exc


async def create(pool: asyncpg.Pool, user_id: uuid.UUID) -> Conversation:
    row = await pool.fetchrow(
        f"INSERT INTO conversations (user_id) VALUES ($1) RETURNING {_COLUMNS}", user_id
    )
    return Conversation(**dict(row))


async def list_page(
    pool: asyncpg.Pool, user_id: uuid.UUID, limit: int, after: Cursor | None
) -> tuple[list[Conversation], Cursor | None]:
    rows = await pool.fetch(
        f"""
        SELECT {_COLUMNS} FROM conversations
        WHERE user_id = $1
          AND ($2::timestamptz IS NULL OR (updated_at, id) < ($2, $3))
        ORDER BY updated_at DESC, id DESC
        LIMIT $4
        """,
        user_id,
        after.updated_at if after else None,
        after.id if after else None,
        limit + 1,
    )
    page = [Conversation(**dict(row)) for row in rows[:limit]]
    has_more = len(rows) > limit
    next_cursor = Cursor(page[-1].updated_at, page[-1].id) if has_more else None
    return page, next_cursor


async def is_owned_by(pool: asyncpg.Pool, conversation_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return bool(
        await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM conversations WHERE id = $1 AND user_id = $2)",
            conversation_id,
            user_id,
        )
    )
