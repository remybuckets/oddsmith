"""App factory.

Run: uvicorn app.main:create_app --factory --proxy-headers
(--proxy-headers plus FORWARDED_ALLOW_IPS set to Railway's proxy range, so the per-IP limit sees
the client's IP rather than the proxy's; uvicorn only trusts 127.0.0.1 by default).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.auth import jwks_verifier
from app.clock import system_clock
from app.config import Settings
from app.db import create_pool
from app.deps import AppDeps
from app.envelope import UnhandledErrorMiddleware, register_error_handlers
from app.orchestrator_port import AnswerFn
from app.routes import conversations, feedback, me, public
from app.supabase_admin import SupabaseAdmin

logger = logging.getLogger(__name__)


def load_answer() -> AnswerFn:
    """The orchestrator lane's answer(), or the canned fake until that lane merges."""
    try:
        from orchestrator import answer  # type: ignore[attr-defined]
    except ImportError:
        from app.fake_orchestrator import answer

        logger.warning("orchestrator.answer not found; using the FAKE orchestrator")
    return answer


@asynccontextmanager
async def open_deps(settings: Settings) -> AsyncIterator[AppDeps]:
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, send_default_pii=False)
    if settings.daily_token_budget is None:
        logger.warning("DAILY_TOKEN_BUDGET is not set; the global token budget is OFF")
    pool = await create_pool(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    http = httpx.AsyncClient()
    try:
        yield AppDeps(
            settings=settings,
            pool=pool,
            redis=redis,
            verifier=jwks_verifier(settings.jwks_url, settings.auth_issuer),
            admin=SupabaseAdmin(settings.supabase_url, settings.supabase_service_role_key, http),
            answer=load_answer(),
            clock=system_clock,
        )
    finally:
        await http.aclose()
        await redis.aclose()
        await pool.close()


def create_app(deps: AppDeps | None = None) -> FastAPI:
    """Pass deps in tests; in production they're built from the environment at startup."""
    settings = deps.settings if deps is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.deps is not None:
            yield
            return
        async with open_deps(settings) as built:
            app.state.deps = built
            yield

    # No generated docs: contracts/openapi.yaml is the only API description.
    app = FastAPI(
        title="Oddsmith API", lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None
    )
    app.state.deps = deps
    app.add_middleware(UnhandledErrorMiddleware)  # added first, so it sits inside CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)
    for router in (me.router, conversations.router, feedback.router, public.router):
        app.include_router(router)
    return app
