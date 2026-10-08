"""Background check that alerts when an ingestion job goes stale (same rules as /health).

Every API replica runs it; a Redis key per job makes sure only one alert goes out per window.
"""

import asyncio
import logging
from typing import Protocol

from app.deps import AppDeps
from app.repos import health
from app.repos.health import JobHealth

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 15 * 60
REALERT_SECONDS = 6 * 3600  # remind every 6h while a job stays stale


class Alerts(Protocol):
    def job_stale(self, job: JobHealth) -> None: ...
    def job_recovered(self, name: str) -> None: ...


def _alert_key(name: str) -> str:
    return f"alert:job_stale:{name}"


async def check_job_health(deps: AppDeps, alerts: Alerts) -> None:
    for job in await health.job_health(deps.pool, deps.clock()):
        key = _alert_key(job.name)
        if job.is_stale:
            if await deps.redis.set(key, "1", nx=True, ex=REALERT_SECONDS):
                alerts.job_stale(job)
        elif await deps.redis.delete(key):
            alerts.job_recovered(job.name)


async def watch_job_health(
    deps: AppDeps, alerts: Alerts, interval: float = CHECK_INTERVAL_SECONDS
) -> None:
    """Runs until cancelled; a failed check is logged and retried next interval."""
    while True:
        try:
            await check_job_health(deps, alerts)
        except Exception:
            logger.exception("job health check failed")
        await asyncio.sleep(interval)
