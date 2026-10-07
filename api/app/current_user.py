"""FastAPI dependency: the signed-in user and their profile."""

from dataclasses import dataclass
from typing import Annotated

import asyncpg
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from app.auth import AuthUser
from app.deps import AppDeps, get_deps
from app.envelope import unauthenticated
from app.repos import profiles
from app.repos.profiles import Profile


@dataclass(frozen=True)
class CurrentUser:
    auth: AuthUser
    profile: Profile

    @property
    def id(self):
        return self.auth.id


def _bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthenticated()
    return token.strip()


async def current_user(
    request: Request, deps: Annotated[AppDeps, Depends(get_deps)]
) -> CurrentUser:
    auth = await run_in_threadpool(deps.verifier.verify, _bearer_token(request))
    try:
        profile = await profiles.ensure(deps.pool, auth.id)
    except asyncpg.ForeignKeyViolationError as exc:
        raise unauthenticated() from exc
    return CurrentUser(auth=auth, profile=profile)


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
DepsDep = Annotated[AppDeps, Depends(get_deps)]
