import pytest

from oddsmith_ingestion.job_runs import run_job


async def test_successful_job_records_success_and_row_count(db):
    # Arrange
    async def work() -> int:
        running = await db.fetchrow("SELECT status, finished_at FROM job_runs")
        assert running["status"] == "running"
        assert running["finished_at"] is None
        return 7

    # Act
    rows = await run_job(db, "seed_reference", work)

    # Assert
    assert rows == 7
    run = await db.fetchrow("SELECT * FROM job_runs")
    assert run["name"] == "seed_reference"
    assert run["status"] == "success"
    assert run["rows"] == 7
    assert run["finished_at"] >= run["started_at"]
    assert run["error"] is None


async def test_failed_job_records_error_and_reraises(db):
    async def work() -> int:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        await run_job(db, "sync_odds", work)

    run = await db.fetchrow("SELECT * FROM job_runs")
    assert run["status"] == "failed"
    assert "provider down" in run["error"]
    assert run["finished_at"] is not None
    assert run["rows"] is None


async def test_cancelled_job_is_marked_failed(db):
    import asyncio

    async def work() -> int:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_job(db, "sync_odds", work)

    assert await db.fetchval("SELECT status FROM job_runs") == "failed"
