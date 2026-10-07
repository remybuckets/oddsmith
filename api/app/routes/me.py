"""/me, /me/break and /onboarding/age."""

import logging
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import limits
from app.clock import next_uk_midnight, to_iso
from app.current_user import CurrentUser, CurrentUserDep, DepsDep
from app.deps import AppDeps
from app.envelope import internal, ok
from app.repos import profiles
from app.repos.profiles import Profile

logger = logging.getLogger(__name__)
router = APIRouter()

BREAK_DURATIONS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


class AgeDeclaration(BaseModel):
    is_over_18: Literal[True]
    accepts_terms: Literal[True]


class BreakRequest(BaseModel):
    duration: Literal["24h", "7d", "30d"]


async def build_me(deps: AppDeps, user: CurrentUser, profile: Profile) -> dict[str, Any]:
    now = deps.clock()
    return {
        "id": str(user.id),
        "email": user.auth.email,
        "age_confirmed": profile.is_age_confirmed,
        "self_excluded_until": to_iso(profile.break_until(now)),
        "usage": {
            "questions_today": await limits.questions_used(deps.redis, user.id, now),
            "daily_limit": deps.settings.daily_question_limit,
            "resets_at": to_iso(next_uk_midnight(now)),
        },
    }


@router.get("/me")
async def get_me(user: CurrentUserDep, deps: DepsDep) -> dict[str, Any]:
    return ok(await build_me(deps, user, user.profile))


@router.post("/onboarding/age")
async def confirm_age(
    _declaration: AgeDeclaration, user: CurrentUserDep, deps: DepsDep
) -> dict[str, Any]:
    profile = await profiles.confirm_age(deps.pool, user.id, deps.clock())
    return ok(await build_me(deps, user, profile))


@router.post("/me/break")
async def take_break(body: BreakRequest, user: CurrentUserDep, deps: DepsDep) -> dict[str, Any]:
    until = deps.clock() + BREAK_DURATIONS[body.duration]
    profile = await profiles.extend_break(deps.pool, user.id, until)
    return ok(await build_me(deps, user, profile))


@router.delete("/me")
async def delete_me(user: CurrentUserDep, deps: DepsDep) -> dict[str, Any]:
    try:
        await deps.admin.delete_user(user.id)
    except Exception as exc:
        logger.exception("account deletion failed for %s", user.id)
        raise internal() from exc
    return ok()
