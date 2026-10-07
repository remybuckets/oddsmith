"""What users see when a dependency fails: friendly errors, nothing leaked, nothing lost."""

import jwt
import pytest

from app.auth import TokenVerifier
from tests.conftest import ISSUER
from tests.sse import parse_sse


class BrokenRedis:
    """Every call fails, as if Redis were down."""

    def __getattr__(self, name):
        async def _fail(*_args, **_kwargs):
            raise ConnectionError("redis down")

        return _fail


class TokenCounterDown:
    """Redis that works except for adding to the token budget."""

    def __init__(self, redis) -> None:
        self._redis = redis

    def __getattr__(self, name):
        return getattr(self._redis, name)

    async def incrby(self, *_args, **_kwargs):
        raise ConnectionError("redis down")


async def test_unexpected_error_is_a_friendly_500(with_deps, make_client, adult):
    async with make_client(with_deps(redis=BrokenRedis())) as http:
        response = await http.get("/me", headers=adult.headers)

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal"
    assert "redis" not in error["message"].lower()


async def test_unreachable_signing_keys_is_internal_not_unauthenticated(
    with_deps, make_client, adult
):
    def unreachable(_token):
        raise jwt.PyJWKClientConnectionError("connection refused")

    verifier = TokenVerifier(unreachable, issuer=ISSUER)
    async with make_client(with_deps(verifier=verifier)) as http:
        response = await http.get("/me", headers=adult.headers)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal"


async def test_answer_still_ends_cleanly_if_token_counter_fails(
    with_deps, make_client, pool, redis, adult
):
    async with make_client(with_deps(redis=TokenCounterDown(redis))) as http:
        conversation_id = (await http.post("/conversations", headers=adult.headers)).json()["data"][
            "id"
        ]
        response = await http.post(
            f"/conversations/{conversation_id}/messages",
            headers=adult.headers,
            json={"content": "Who's injured?"},
        )

    assert parse_sse(response.text)[-1][0] == "message_end"
    assert await pool.fetchval("SELECT count(*) FROM messages") == 2


async def test_failed_refund_still_sends_error_event(with_deps, make_client, redis, adult):
    class RefundDown(TokenCounterDown):
        async def decr(self, *_args, **_kwargs):
            raise ConnectionError("redis down")

    async def failing(history, question):
        yield {"type": "error", "error": {"code": "internal", "message": "x"}}

    async with make_client(with_deps(redis=RefundDown(redis), answer=failing)) as http:
        conversation_id = (await http.post("/conversations", headers=adult.headers)).json()["data"][
            "id"
        ]
        response = await http.post(
            f"/conversations/{conversation_id}/messages",
            headers=adult.headers,
            json={"content": "Who's injured?"},
        )

    assert [name for name, _ in parse_sse(response.text)] == ["message_start", "error"]


@pytest.mark.parametrize("method", ["put", "patch"])
async def test_wrong_method_uses_envelope(client, method):
    response = await client.request(method.upper(), "/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "invalid_input"


async def test_question_is_refunded_if_setup_fails_before_streaming(
    with_deps, make_client, redis, adult, monkeypatch
):
    from app.repos import messages

    async def broken_history(*_args):
        raise ConnectionError("db down")

    monkeypatch.setattr(messages, "recent_history", broken_history)
    async with make_client(with_deps()) as http:
        conversation_id = (await http.post("/conversations", headers=adult.headers)).json()["data"][
            "id"
        ]
        response = await http.post(
            f"/conversations/{conversation_id}/messages",
            headers=adult.headers,
            json={"content": "Who's injured?"},
        )

    assert response.status_code == 500
    assert int(await redis.get(f"questions:2026-10-10:{adult.id}") or 0) == 0


async def test_500_keeps_cors_headers_so_browser_sees_message(with_deps, make_client, adult):
    async with make_client(with_deps(redis=BrokenRedis())) as http:
        response = await http.get(
            "/me", headers={**adult.headers, "Origin": "http://localhost:3000"}
        )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.json()["error"]["code"] == "internal"


async def test_validation_errors_do_not_log_user_input(client, adult, caplog):
    import logging

    conversation_id = (await client.post("/conversations", headers=adult.headers)).json()["data"][
        "id"
    ]
    with caplog.at_level(logging.INFO):
        await client.post(
            f"/conversations/{conversation_id}/messages",
            headers=adult.headers,
            json={"content": "my-secret-question" * 100},
        )

    assert "my-secret-question" not in caplog.text
