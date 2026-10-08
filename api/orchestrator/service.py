"""answer(): the orchestrator interface the backend calls, wired to Postgres and Claude."""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import anthropic
import asyncpg

from orchestrator.config import OrchestratorSettings
from orchestrator.loop import ERROR_MESSAGE, AnswerDeps, run_answer
from orchestrator.model_client import AnthropicModel

logger = logging.getLogger(__name__)

POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 5

# One pool per event loop (asyncpg pools are bound to the loop that made them). Stored as a
# task so concurrent first requests share a single pool creation.
_POOLS: dict[asyncio.AbstractEventLoop, asyncio.Task] = {}


async def _pool(dsn: str) -> asyncpg.Pool:
    global _POOLS
    loop = asyncio.get_running_loop()
    if loop not in _POOLS:
        creating = asyncio.ensure_future(
            asyncpg.create_pool(dsn, min_size=POOL_MIN_SIZE, max_size=POOL_MAX_SIZE)
        )
        _POOLS = {**_POOLS, loop: creating}
    try:
        return await _POOLS[loop]
    except Exception:
        _POOLS = {k: v for k, v in _POOLS.items() if k is not loop}  # retry next time
        raise


async def _default_deps() -> AnswerDeps:
    settings = OrchestratorSettings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set for the orchestrator")
    pool = await _pool(settings.database_url)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return AnswerDeps(
        model=AnthropicModel(client),
        connection=lambda: pool.acquire(),
        settings=settings,
        clock=lambda: datetime.now(UTC),
    )


async def answer(history: list[dict[str, str]], question: str) -> AsyncIterator[dict[str, Any]]:
    """The contract in contracts/README.md: tool_status / text_delta / card events, then one
    sources event and one usage event; on failure, one error event and stop."""
    try:
        deps = await _default_deps()
    except Exception:
        logger.exception("orchestrator setup failed")
        yield {"type": "error", "error": {"code": "internal", "message": ERROR_MESSAGE}}
        return
    async for event in run_answer(deps, history, question):
        yield event
