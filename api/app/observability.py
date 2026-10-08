"""Sentry: errors and stale-job alerts, with user content and credentials stripped."""

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.transport import Transport

from app.config import Settings
from app.repos.health import JobHealth

logger = logging.getLogger(__name__)

TRACES_SAMPLE_RATE = 0.1  # enough to watch time-to-first-token without burning quota
_DROPPED_REQUEST_FIELDS = ("data", "cookies")
_DROPPED_HEADERS = {"authorization", "cookie", "x-forwarded-for", "x-real-ip"}


def scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Questions, tokens, cookies, emails and IPs never leave the server. Returns a copy."""
    scrubbed = dict(event)
    request = event.get("request")
    if isinstance(request, dict):
        cleaned = {k: v for k, v in request.items() if k not in _DROPPED_REQUEST_FIELDS}
        headers = request.get("headers")
        if isinstance(headers, dict):
            cleaned["headers"] = {
                k: v for k, v in headers.items() if k.lower() not in _DROPPED_HEADERS
            }
        scrubbed["request"] = cleaned
    user = event.get("user")
    if isinstance(user, dict):
        scrubbed["user"] = {"id": user["id"]} if "id" in user else {}
    return scrubbed


def init_sentry(settings: Settings, transport: Transport | None = None) -> bool:
    if not settings.sentry_dsn:
        logger.warning("SENTRY_DSN is not set; errors are only logged")
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=TRACES_SAMPLE_RATE,
        before_send=scrub_event,
        transport=transport,
    )
    return True


class SentryAlerts:
    """Stale jobs become Sentry warnings tagged alert=job_stale, one issue per job."""

    def job_stale(self, job: JobHealth) -> None:
        last = job.last_success_at.isoformat() if job.last_success_at else "never"
        logger.warning("ingestion job %s is stale (last success: %s)", job.name, last)
        sentry_sdk.capture_message(
            f"Ingestion job {job.name} is stale (last success: {last})",
            level="warning",
            tags={"alert": "job_stale", "job": job.name},
            fingerprint=["job_stale", job.name],
        )

    def job_recovered(self, name: str) -> None:
        logger.info("ingestion job %s has recovered", name)
