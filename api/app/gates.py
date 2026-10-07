"""Checks before an answer streams, in the order api/CLAUDE.md sets."""

import uuid
from datetime import datetime

from app import limits
from app.deps import AppDeps
from app.envelope import ApiError, ErrorCode
from app.repos.profiles import Profile

AGE_MESSAGE = "Please confirm you're 18 or over before you start chatting."
BREAK_MESSAGE = "You're taking a break from Oddsmith. Chat opens again when it ends."


async def check_chat_gates(
    deps: AppDeps, user_id: uuid.UUID, profile: Profile, ip: str, now: datetime
) -> None:
    """Authenticated (already) → age → break → per-IP rate → daily questions → token budget."""
    if not profile.is_age_confirmed:
        raise ApiError(403, ErrorCode.AGE_NOT_CONFIRMED, AGE_MESSAGE)
    break_until = profile.break_until(now)
    if break_until is not None:
        raise ApiError(403, ErrorCode.ON_BREAK, BREAK_MESSAGE, break_until)
    settings = deps.settings
    await limits.check_rate_limit(deps.redis, ip, now, settings.per_ip_requests_per_minute)
    await limits.check_daily_questions(deps.redis, user_id, now, settings.daily_question_limit)
    await limits.check_token_budget(deps.redis, now, settings.daily_token_budget)
