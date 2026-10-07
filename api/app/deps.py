"""Everything a request needs, built once at startup and swapped out in tests."""

import uuid
from dataclasses import dataclass
from typing import Protocol

import asyncpg
from fastapi import Request
from redis.asyncio import Redis

from app.auth import TokenVerifier
from app.clock import Clock
from app.config import Settings
from app.orchestrator_port import AnswerFn


class UserAdmin(Protocol):
    async def delete_user(self, user_id: uuid.UUID) -> None: ...


@dataclass(frozen=True)
class AppDeps:
    settings: Settings
    pool: asyncpg.Pool
    redis: Redis
    verifier: TokenVerifier
    admin: UserAdmin
    answer: AnswerFn
    clock: Clock


def get_deps(request: Request) -> AppDeps:
    return request.app.state.deps
