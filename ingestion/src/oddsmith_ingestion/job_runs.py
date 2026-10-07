"""Every job runs through run_job so job_runs records running -> success/failed."""

import logging
from collections.abc import Awaitable, Callable

import asyncpg

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 2000


async def run_job(pool: asyncpg.Pool, name: str, work: Callable[[], Awaitable[int]]) -> int:
    """Run `work` (which returns the number of rows written) and record the outcome."""
    run_id = await pool.fetchval(
        "INSERT INTO job_runs (name, status) VALUES ($1, 'running') RETURNING id", name
    )
    logger.info("job %s started (run %s)", name, run_id)
    try:
        rows = await work()
    except BaseException as exc:  # includes cancellation and Ctrl-C: never leave 'running'
        logger.exception("job %s failed (run %s)", name, run_id)
        await _mark_failed(pool, run_id, exc)
        raise
    await pool.execute(
        "UPDATE job_runs SET status = 'success', finished_at = now(), rows = $2 WHERE id = $1",
        run_id,
        rows,
    )
    logger.info("job %s succeeded (run %s): %s rows", name, run_id, rows)
    return rows


async def _mark_failed(pool: asyncpg.Pool, run_id: int, exc: BaseException) -> None:
    """Record the failure without masking the original error if the update itself fails."""
    try:
        await pool.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = now(), error = $2 WHERE id = $1",
            run_id,
            f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
        )
    except Exception:
        logger.exception("could not mark job run %s failed", run_id)
