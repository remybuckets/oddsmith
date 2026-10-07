"""messages and usage_daily: the chat history and per-user daily totals."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import asyncpg

from app.orchestrator_port import ChatTurn

MAX_HISTORY_MESSAGES = 20  # bounds prompt size and cost on long chats
TITLE_MAX_CHARS = 80


@dataclass(frozen=True)
class StoredMessage:
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    feedback: int | None


@dataclass(frozen=True)
class Usage:
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def from_event(event: dict[str, Any]) -> "Usage":
        return Usage(
            model=event.get("model"),
            tokens_in=int(event.get("tokens_in") or 0),
            tokens_out=int(event.get("tokens_out") or 0),
            tool_calls=list(event.get("tool_calls") or []),
        )

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass(frozen=True)
class Exchange:
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    assistant_message_id: uuid.UUID
    question: str
    answer: str
    usage: Usage
    day: date  # UK calendar date the question counts against


async def list_for_conversation(
    pool: asyncpg.Pool, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> list[StoredMessage]:
    rows = await pool.fetch(
        """
        SELECT m.id, m.role, m.content, m.created_at, f.rating AS feedback
        FROM messages m
        LEFT JOIN feedback f ON f.message_id = m.id AND f.user_id = $2
        WHERE m.conversation_id = $1
        ORDER BY m.created_at, m.id
        """,
        conversation_id,
        user_id,
    )
    return [StoredMessage(**dict(row)) for row in rows]


async def recent_history(pool: asyncpg.Pool, conversation_id: uuid.UUID) -> list[ChatTurn]:
    rows = await pool.fetch(
        """
        SELECT role, content FROM (
            SELECT role, content, created_at FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT $2
        ) recent
        ORDER BY created_at
        """,
        conversation_id,
        MAX_HISTORY_MESSAGES,
    )
    return [ChatTurn(role=row["role"], content=row["content"]) for row in rows]


async def save_exchange(pool: asyncpg.Pool, exchange: Exchange) -> None:
    """Question, answer, daily usage and the chat's title/recency, all or nothing."""
    usage = exchange.usage
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES ($1, 'user', $2, clock_timestamp())
            """,
            exchange.conversation_id,
            exchange.question,
        )
        await conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, tool_calls, model,
                                  tokens_in, tokens_out, created_at)
            VALUES ($1, $2, 'assistant', $3, $4, $5, $6, $7, clock_timestamp())
            """,
            exchange.assistant_message_id,
            exchange.conversation_id,
            exchange.answer,
            usage.tool_calls,
            usage.model,
            usage.tokens_in,
            usage.tokens_out,
        )
        await conn.execute(
            """
            INSERT INTO usage_daily (user_id, date, questions, tokens_in, tokens_out)
            VALUES ($1, $2, 1, $3, $4)
            ON CONFLICT (user_id, date) DO UPDATE
            SET questions  = usage_daily.questions + 1,
                tokens_in  = usage_daily.tokens_in + EXCLUDED.tokens_in,
                tokens_out = usage_daily.tokens_out + EXCLUDED.tokens_out
            """,
            exchange.user_id,
            exchange.day,
            usage.tokens_in,
            usage.tokens_out,
        )
        await conn.execute(
            "UPDATE conversations SET updated_at = now(), title = COALESCE(title, $2) WHERE id = $1",
            exchange.conversation_id,
            exchange.question.strip()[:TITLE_MAX_CHARS],
        )
