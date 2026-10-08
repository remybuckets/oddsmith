"""Production wiring: the Supabase admin client and the orchestrator loader."""

import builtins
import uuid

import httpx
import pytest

from app.fake_orchestrator import answer as fake_answer
from app.main import load_answer
from app.supabase_admin import SupabaseAdmin
from orchestrator import answer as real_answer


def _admin(handler) -> SupabaseAdmin:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseAdmin("http://sb.test/", "service-key", http)


async def test_admin_deletes_user_with_service_role():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    user_id = uuid.uuid4()
    await _admin(handler).delete_user(user_id)

    [request] = seen
    assert request.method == "DELETE"
    assert str(request.url) == f"http://sb.test/auth/v1/admin/users/{user_id}"
    assert request.headers["apikey"] == "service-key"
    assert request.headers["authorization"] == "Bearer service-key"


async def test_admin_treats_missing_user_as_deleted():
    await _admin(lambda _r: httpx.Response(404)).delete_user(uuid.uuid4())


async def test_admin_raises_on_server_error():
    with pytest.raises(httpx.HTTPStatusError):
        await _admin(lambda _r: httpx.Response(500)).delete_user(uuid.uuid4())


def test_load_answer_uses_the_orchestrator_lane():
    assert load_answer() is real_answer


def test_load_answer_falls_back_to_fake_without_the_orchestrator(monkeypatch):
    real_import = builtins.__import__

    def no_orchestrator(name, *args, **kwargs):
        if name == "orchestrator":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_orchestrator)
    assert load_answer() is fake_answer


async def test_app_builds_its_own_deps_from_the_environment(monkeypatch, settings):
    from app.auth import TokenVerifier
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("SUPABASE_URL", "http://sb.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setenv("DAILY_TOKEN_BUDGET", "")
    monkeypatch.setenv("SENTRY_DSN", "")
    app = create_app()

    async with app.router.lifespan_context(app):
        deps = app.state.deps
        assert deps.settings.daily_token_budget is None
        assert isinstance(deps.verifier, TokenVerifier)
        assert deps.answer is real_answer
        assert await deps.pool.fetchval("SELECT 1") == 1
        assert not app.state.health_watcher.done()
    assert app.state.health_watcher.cancelled()


async def test_injected_deps_are_used_as_is(deps):
    from app.main import create_app

    app = create_app(deps)
    async with app.router.lifespan_context(app):
        assert app.state.deps is deps
