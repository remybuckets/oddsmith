"""feedback: one rating per user per assistant message; re-posting replaces it."""

import uuid

import asyncpg


async def upsert(
    pool: asyncpg.Pool, user_id: uuid.UUID, message_id: uuid.UUID, rating: int, note: str | None
) -> bool:
    """False if the message isn't an assistant message in one of the user's chats."""
    row_id = await pool.fetchval(
        """
        INSERT INTO feedback (message_id, user_id, rating, note)
        SELECT m.id, $2, $3, $4
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE m.id = $1 AND c.user_id = $2 AND m.role = 'assistant'
        ON CONFLICT (message_id, user_id) DO UPDATE
        SET rating = EXCLUDED.rating, note = EXCLUDED.note, created_at = now()
        RETURNING id
        """,
        message_id,
        user_id,
        rating,
        note,
    )
    return row_id is not None
