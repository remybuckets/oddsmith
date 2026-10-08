"""Sentry for the worker. Off unless SENTRY_DSN is set.

Errors logged with logger.exception (every failed job, see job_runs.py) become Sentry events
through the default logging integration. Provider keys are scrubbed: The Odds API takes its
key in the query string (apiKey=...), which HTTP breadcrumbs would otherwise record.
"""

import re
from typing import Any

import sentry_sdk

_SECRET_QUERY = re.compile(r"(apiKey=)[^&\s'\"]+", re.IGNORECASE)
_SECRET_HEADERS = {"x-apisports-key", "authorization"}
FILTERED = "[Filtered]"


def init_sentry(dsn: str) -> bool:
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        server_name="ingestion",
        send_default_pii=False,
        traces_sample_rate=0,
        before_send=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
    )
    return True


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    return _scrub(event)


def scrub_breadcrumb(crumb: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    return _scrub(crumb)


def _scrub(value: Any, key: str | None = None) -> Any:
    """A copy of `value` with secret query params and auth headers replaced."""
    if key is not None and key.lower() in _SECRET_HEADERS:
        return FILTERED
    if isinstance(value, dict):
        return {k: _scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        return _SECRET_QUERY.sub(rf"\g<1>{FILTERED}", value)
    return value
