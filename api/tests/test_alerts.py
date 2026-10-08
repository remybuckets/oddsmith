"""Stale-job alerts: once per job per re-alert window, shared across API replicas via Redis."""

import asyncio
from datetime import timedelta

from app.alerts import REALERT_SECONDS, check_job_health, watch_job_health
from tests.conftest import NOW


async def _fresh_jobs(pool, *, except_job=None):
    for name in (
        "seed_reference",
        "backfill_season",
        "sync_fixtures",
        "sync_results",
        "sync_availability",
        "sync_odds",
        "sync_btts",
    ):
        if name != except_job:
            await pool.execute(
                "INSERT INTO job_runs (name, finished_at, status) VALUES ($1, $2, 'success')",
                name,
                NOW - timedelta(minutes=5),
            )


class Recorder:
    def __init__(self) -> None:
        self.stale: list[str] = []
        self.recovered: list[str] = []

    def job_stale(self, job) -> None:
        self.stale.append(job.name)

    def job_recovered(self, name: str) -> None:
        self.recovered.append(name)


async def test_alerts_once_for_a_stale_job(deps, pool):
    await _fresh_jobs(pool, except_job="sync_odds")
    recorder = Recorder()

    await check_job_health(deps, recorder)
    await check_job_health(deps, recorder)

    assert recorder.stale == ["sync_odds"]


async def test_second_replica_does_not_repeat_the_alert(deps, pool, with_deps):
    await _fresh_jobs(pool, except_job="sync_odds")
    first, second = Recorder(), Recorder()

    await check_job_health(deps, first)
    await check_job_health(with_deps(), second)  # same Redis, another process

    assert (first.stale, second.stale) == (["sync_odds"], [])


async def test_realerts_after_window_while_still_stale(deps, pool, redis):
    await _fresh_jobs(pool, except_job="sync_odds")
    recorder = Recorder()
    await check_job_health(deps, recorder)
    assert 0 < await redis.ttl("alert:job_stale:sync_odds") <= REALERT_SECONDS

    await redis.delete("alert:job_stale:sync_odds")  # window expired
    await check_job_health(deps, recorder)

    assert recorder.stale == ["sync_odds", "sync_odds"]


async def test_recovery_is_reported_and_rearms_the_alert(deps, pool):
    await _fresh_jobs(pool, except_job="sync_odds")
    recorder = Recorder()
    await check_job_health(deps, recorder)

    await pool.execute(
        "INSERT INTO job_runs (name, finished_at, status) VALUES ('sync_odds', $1, 'success')",
        NOW - timedelta(minutes=1),
    )
    await check_job_health(deps, recorder)
    await check_job_health(deps, recorder)

    assert recorder.recovered == ["sync_odds"]


async def test_no_alerts_when_everything_is_fresh(deps, pool):
    await _fresh_jobs(pool)
    recorder = Recorder()

    await check_job_health(deps, recorder)

    assert (recorder.stale, recorder.recovered) == ([], [])


async def test_watcher_keeps_running_after_a_failed_check(deps, pool, with_deps):
    class FlakyRedis:
        def __init__(self, real) -> None:
            self.real, self.calls = real, 0

        def __getattr__(self, name):
            return getattr(self.real, name)

        async def set(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("redis blip")
            return await self.real.set(*args, **kwargs)

    await _fresh_jobs(pool, except_job="sync_odds")
    flaky = FlakyRedis(deps.redis)
    recorder = Recorder()

    task = asyncio.create_task(watch_job_health(with_deps(redis=flaky), recorder, interval=0.01))
    for _ in range(100):
        if recorder.stale:
            break
        await asyncio.sleep(0.01)
    task.cancel()

    assert recorder.stale == ["sync_odds"]
