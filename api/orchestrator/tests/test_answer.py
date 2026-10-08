import inspect
from contextlib import asynccontextmanager

import pytest

import orchestrator
from orchestrator import service
from orchestrator.config import OrchestratorSettings
from orchestrator.loop import AnswerDeps
from orchestrator.tests.fake_model import Scripted, ScriptedModel
from orchestrator.tests.seed import NOW


def test_answer_is_exported_with_the_contract_signature():
    assert inspect.isasyncgenfunction(orchestrator.answer)
    assert list(inspect.signature(orchestrator.answer).parameters) == ["history", "question"]


@pytest.mark.asyncio
async def test_answer_runs_the_loop_with_default_deps(conn, monkeypatch):
    @asynccontextmanager
    async def connection():
        yield conn

    deps = AnswerDeps(
        model=ScriptedModel([Scripted(chunks=("Hello.",))]),
        connection=connection,
        settings=OrchestratorSettings(),
        clock=lambda: NOW,
    )

    async def default_deps():
        return deps

    monkeypatch.setattr(service, "_default_deps", default_deps)
    events = [e async for e in orchestrator.answer([], "Hi")]

    assert [e["type"] for e in events] == ["text_delta", "sources", "usage"]


@pytest.mark.asyncio
async def test_setup_failure_is_one_error_event(monkeypatch, caplog):
    async def broken():
        raise RuntimeError("no database")

    monkeypatch.setattr(service, "_default_deps", broken)
    events = [e async for e in orchestrator.answer([], "Hi")]

    assert events == [
        {
            "type": "error",
            "error": {
                "code": "internal",
                "message": "Oddsmith couldn't finish that answer. Please try again.",
            },
        }
    ]
    assert "no database" in caplog.text


@pytest.mark.asyncio
async def test_missing_database_url_fails_setup(monkeypatch):
    monkeypatch.setattr(
        service, "OrchestratorSettings", lambda: OrchestratorSettings(database_url="")
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await service._default_deps()


@pytest.mark.asyncio
async def test_pool_is_created_once_per_event_loop(monkeypatch):
    created = []

    async def fake_create_pool(dsn, **kwargs):
        created.append(dsn)
        return object()

    monkeypatch.setattr(service.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(service, "_POOLS", {})

    first = await service._pool("postgresql://example/db")
    second = await service._pool("postgresql://example/db")

    assert first is second
    assert created == ["postgresql://example/db"]


@pytest.mark.asyncio
async def test_default_deps_wire_settings_pool_and_claude(monkeypatch):
    async def fake_pool(dsn):
        return "pool"

    monkeypatch.setattr(
        service,
        "OrchestratorSettings",
        lambda: OrchestratorSettings(
            database_url="postgresql://example/db", anthropic_api_key="test-key"
        ),
    )
    monkeypatch.setattr(service, "_pool", fake_pool)

    deps = await service._default_deps()

    assert deps.settings.database_url == "postgresql://example/db"
    assert deps.clock().tzinfo is not None
    assert type(deps.model).__name__ == "AnthropicModel"
