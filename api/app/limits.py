"""Redis counters: per-IP rate limit, daily questions per user, global daily token budget."""

import uuid
from datetime import datetime

from redis.asyncio import Redis

from app.clock import next_uk_midnight, uk_date
from app.envelope import ApiError, ErrorCode

COUNTER_TTL_SECONDS = 2 * 24 * 3600  # outlives the UK day it counts, whatever the DST shift
RATE_WINDOW_SECONDS = 60

RATE_LIMITED_MESSAGE = "You're sending questions too quickly. Give it a minute and try again."
DAILY_LIMIT_MESSAGE = "That's your questions for today. You get a fresh set at midnight."
BUDGET_MESSAGE = "Oddsmith has had a busy day. We'll be back tomorrow."


def questions_key(user_id: uuid.UUID, now: datetime) -> str:
    return f"questions:{uk_date(now).isoformat()}:{user_id}"


def tokens_key(now: datetime) -> str:
    return f"tokens:{uk_date(now).isoformat()}"


def _rate_key(ip: str, window_start: int) -> str:
    return f"ip:{ip}:{window_start}"


async def questions_used(redis: Redis, user_id: uuid.UUID, now: datetime) -> int:
    return int(await redis.get(questions_key(user_id, now)) or 0)


async def check_rate_limit(redis: Redis, ip: str, now: datetime, per_minute: int) -> None:
    """Fixed one-minute window per IP; counts every attempt that reaches this gate."""
    window_start = int(now.timestamp()) // RATE_WINDOW_SECONDS * RATE_WINDOW_SECONDS
    key = _rate_key(ip, window_start)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, RATE_WINDOW_SECONDS)
    if count > per_minute:
        retry_at = datetime.fromtimestamp(window_start + RATE_WINDOW_SECONDS, tz=now.tzinfo)
        raise ApiError(429, ErrorCode.RATE_LIMITED, RATE_LIMITED_MESSAGE, retry_at)


def _daily_limit_error(now: datetime) -> ApiError:
    return ApiError(429, ErrorCode.DAILY_LIMIT_REACHED, DAILY_LIMIT_MESSAGE, next_uk_midnight(now))


async def check_daily_questions(
    redis: Redis, user_id: uuid.UUID, now: datetime, limit: int
) -> None:
    if await questions_used(redis, user_id, now) >= limit:
        raise _daily_limit_error(now)


async def check_token_budget(redis: Redis, now: datetime, budget: int | None) -> None:
    if budget is None:
        return
    if int(await redis.get(tokens_key(now)) or 0) >= budget:
        raise ApiError(503, ErrorCode.BUDGET_EXHAUSTED, BUDGET_MESSAGE, next_uk_midnight(now))


async def reserve_question(redis: Redis, user_id: uuid.UUID, now: datetime, limit: int) -> int:
    """Atomically take one of today's questions; returns how many are now used."""
    key = questions_key(user_id, now)
    used = await redis.incr(key)
    await redis.expire(key, COUNTER_TTL_SECONDS)
    if used > limit:
        await redis.decr(key)
        raise _daily_limit_error(now)
    return used


async def refund_question(redis: Redis, user_id: uuid.UUID, now: datetime) -> None:
    await redis.decr(questions_key(user_id, now))


async def record_tokens(redis: Redis, now: datetime, tokens: int) -> None:
    key = tokens_key(now)
    await redis.incrby(key, tokens)
    await redis.expire(key, COUNTER_TTL_SECONDS)
