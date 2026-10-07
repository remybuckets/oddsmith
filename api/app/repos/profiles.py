"""profiles: one row per Supabase user, holding 18+ confirmation, terms and take-a-break."""

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_COLUMNS = "id, age_confirmed_at, terms_accepted_at, self_excluded_until"


@dataclass(frozen=True)
class Profile:
    id: uuid.UUID
    age_confirmed_at: datetime | None
    terms_accepted_at: datetime | None
    self_excluded_until: datetime | None

    @property
    def is_age_confirmed(self) -> bool:
        return self.age_confirmed_at is not None and self.terms_accepted_at is not None

    def break_until(self, now: datetime) -> datetime | None:
        """End of an active break, or None if not on one."""
        if self.self_excluded_until is None or self.self_excluded_until <= now:
            return None
        return self.self_excluded_until


def _to_profile(row: asyncpg.Record) -> Profile:
    return Profile(**dict(row))


async def ensure(pool: asyncpg.Pool, user_id: uuid.UUID) -> Profile:
    """Fetch the profile, creating it on the user's first authenticated request.

    Raises asyncpg.ForeignKeyViolationError if the Supabase user no longer exists.
    """
    row = await pool.fetchrow(f"SELECT {_COLUMNS} FROM profiles WHERE id = $1", user_id)
    if row is None:
        row = await pool.fetchrow(
            f"""
            INSERT INTO profiles (id) VALUES ($1)
            ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id
            RETURNING {_COLUMNS}
            """,
            user_id,
        )
    return _to_profile(row)


async def confirm_age(pool: asyncpg.Pool, user_id: uuid.UUID, now: datetime) -> Profile:
    row = await pool.fetchrow(
        f"""
        UPDATE profiles
        SET age_confirmed_at  = COALESCE(age_confirmed_at, $2),
            terms_accepted_at = COALESCE(terms_accepted_at, $2)
        WHERE id = $1
        RETURNING {_COLUMNS}
        """,
        user_id,
        now,
    )
    return _to_profile(row)


async def extend_break(pool: asyncpg.Pool, user_id: uuid.UUID, until: datetime) -> Profile:
    """Set the break end, never moving it earlier: a break can't be shortened."""
    row = await pool.fetchrow(
        f"""
        UPDATE profiles
        SET self_excluded_until = GREATEST(self_excluded_until, $2)
        WHERE id = $1
        RETURNING {_COLUMNS}
        """,
        user_id,
        until,
    )
    return _to_profile(row)
