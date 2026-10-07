"""Shared fixtures: the backend test database, fake Redis, signed tokens and an app client."""

import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import fakeredis
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import TokenVerifier
from app.config import Settings
from app.db import create_pool
from app.deps import AppDeps
from app.fake_orchestrator import answer as fake_answer
from app.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:54322/oddsmith_test_backend",
)
SUPABASE_URL = "http://supabase.test"
ISSUER = f"{SUPABASE_URL}/auth/v1"
NOW = datetime(2026, 10, 10, 11, 0, tzinfo=UTC)  # Saturday, 12:00 in London (BST)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeAdmin:
    """Stands in for the Supabase admin API: deleting the auth user cascades like production."""

    def __init__(self, pool) -> None:
        self.pool = pool
        self.deleted: list[uuid.UUID] = []

    async def delete_user(self, user_id: uuid.UUID) -> None:
        self.deleted.append(user_id)
        await self.pool.execute("DELETE FROM auth.users WHERE id = $1", user_id)


@dataclass(frozen=True)
class TestUser:
    id: uuid.UUID
    email: str
    headers: dict[str, str]


@pytest.fixture(scope="session")
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
async def pool() -> AsyncIterator:
    db_pool = await create_pool(TEST_DATABASE_URL)
    yield db_pool
    await db_pool.close()


@pytest.fixture(autouse=True)
async def clean_db(pool) -> None:
    await pool.execute("TRUNCATE auth.users, job_runs, fixtures, teams CASCADE")


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        supabase_url=SUPABASE_URL,
        supabase_service_role_key="service-role-test",
        redis_url="redis://unused",
        daily_question_limit=15,
        per_ip_requests_per_minute=10,
        daily_token_budget=100_000,
    )


@pytest.fixture
def admin(pool) -> FakeAdmin:
    return FakeAdmin(pool)


@pytest.fixture
def deps(settings, pool, redis, signing_key, admin, clock) -> AppDeps:
    verifier = TokenVerifier(lambda _token: signing_key.public_key(), issuer=ISSUER)
    return AppDeps(
        settings=settings,
        pool=pool,
        redis=redis,
        verifier=verifier,
        admin=admin,
        answer=fake_answer,
        clock=clock,
    )


@pytest.fixture
def make_client() -> Callable[..., httpx.AsyncClient]:
    def _make(app_deps: AppDeps, ip: str = "203.0.113.7") -> httpx.AsyncClient:
        # raise_app_exceptions=False: see the 500 the client gets, as in production
        transport = httpx.ASGITransport(
            app=create_app(app_deps), client=(ip, 51000), raise_app_exceptions=False
        )
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.fixture
async def client(deps, make_client) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(deps) as http:
        yield http


@pytest.fixture
def with_deps(deps) -> Callable[..., AppDeps]:
    """Copy of the default deps with some fields swapped, e.g. with_deps(answer=broken)."""
    return lambda **changes: replace(deps, **changes)


@pytest.fixture
def make_token(signing_key) -> Callable[..., str]:
    def _make(
        user_id: uuid.UUID,
        email: str = "punter@example.com",
        expires_in: int = 3600,
        issuer: str = ISSUER,
        audience: str = "authenticated",
        key: ec.EllipticCurvePrivateKey | None = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": str(user_id),
            "email": email,
            "aud": audience,
            "iss": issuer,
            "role": "authenticated",
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(claims, key or signing_key, algorithm="ES256")

    return _make


@pytest.fixture
def make_user(pool, make_token) -> Callable[..., object]:
    async def _make(email: str = "punter@example.com", age_confirmed: bool = False) -> TestUser:
        user_id = uuid.uuid4()
        await pool.execute("INSERT INTO auth.users (id) VALUES ($1)", user_id)
        if age_confirmed:
            await pool.execute(
                "INSERT INTO profiles (id, age_confirmed_at, terms_accepted_at) "
                "VALUES ($1, now(), now())",
                user_id,
            )
        token = make_token(user_id, email=email)
        return TestUser(id=user_id, email=email, headers={"Authorization": f"Bearer {token}"})

    return _make


@pytest.fixture
async def user(make_user) -> TestUser:
    """Signed in, no profile row yet, not onboarded."""
    return await make_user()


@pytest.fixture
async def adult(make_user) -> TestUser:
    """Signed in and past the 18+ declaration."""
    return await make_user(email="adult@example.com", age_confirmed=True)
