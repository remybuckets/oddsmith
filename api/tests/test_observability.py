"""Sentry wiring: errors reach Sentry without questions, tokens or emails."""

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from app.config import Settings
from app.observability import SentryAlerts, init_sentry, scrub_event
from app.repos.health import JobHealth
from tests.conftest import NOW


class CapturingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


@pytest.fixture
def sentry_events(settings):
    transport = CapturingTransport()
    enabled = settings.model_copy(update={"sentry_dsn": "https://public@sentry.example/1"})
    assert init_sentry(enabled, transport=transport) is True
    yield transport.events
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # back to a disabled client for other tests


def test_no_dsn_means_sentry_off(settings):
    assert init_sentry(settings.model_copy(update={"sentry_dsn": ""})) is False


def test_environment_and_release_come_from_railway(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")
    settings = Settings(
        _env_file=None, database_url="x", supabase_url="y", supabase_service_role_key="z"
    )
    assert (settings.environment, settings.release) == ("production", "abc123")


def test_scrub_removes_bodies_tokens_and_emails():
    event = {
        "request": {
            "data": '{"content": "my question"}',
            "cookies": {"sb": "secret"},
            "headers": {"Authorization": "Bearer abc", "Cookie": "x", "User-Agent": "ua"},
            "query_string": "cursor=abc",
        },
        "user": {"id": "u1", "email": "a@b.co", "ip_address": "1.2.3.4"},
    }

    scrubbed = scrub_event(event, {})

    assert scrubbed["request"] == {"headers": {"User-Agent": "ua"}, "query_string": "cursor=abc"}
    assert scrubbed["user"] == {"id": "u1"}
    assert event["request"]["data"]  # the original isn't mutated


async def test_unhandled_error_reaches_sentry_scrubbed(
    sentry_events, with_deps, make_client, adult
):
    class BrokenRedis:
        def __getattr__(self, name):
            async def _fail(*_a, **_k):
                raise ConnectionError("redis down")

            return _fail

    async with make_client(with_deps(redis=BrokenRedis())) as http:
        response = await http.get("/me", headers=adult.headers)
    sentry_sdk.flush()

    assert response.status_code == 500
    [event] = [e for e in sentry_events if e.get("exception")]
    assert event["exception"]["values"][-1]["type"] == "ConnectionError"
    assert event["user"] == {"id": str(adult.id)}
    assert "Authorization" not in str(event.get("request", {}))


def test_stale_job_alert_is_tagged_for_alert_rules(sentry_events):
    SentryAlerts().job_stale(JobHealth("sync_odds", NOW, True))
    sentry_sdk.flush()

    [event] = sentry_events
    assert event["level"] == "warning"
    assert event["tags"]["alert"] == "job_stale"
    assert event["tags"]["job"] == "sync_odds"
    assert event["fingerprint"] == ["job_stale", "sync_odds"]
    assert "sync_odds" in event["message"]


def test_recovery_is_logged_not_sent(sentry_events, caplog):
    import logging

    with caplog.at_level(logging.INFO):
        SentryAlerts().job_recovered("sync_odds")
    sentry_sdk.flush()

    assert "sync_odds" in caplog.text
    assert sentry_events == []
