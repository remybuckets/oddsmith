"""Gates on POST /conversations/{id}/messages, checked in order before streaming starts."""

from datetime import timedelta

import pytest

from tests.conftest import NOW

QUESTION = {"content": "How has Saka done away from home this season?"}


async def _conversation(client, user) -> str:
    return (await client.post("/conversations", headers=user.headers)).json()["data"]["id"]


async def _ask(client, user, conversation_id, body=QUESTION):
    return await client.post(
        f"/conversations/{conversation_id}/messages", headers=user.headers, json=body
    )


def _assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == code


async def test_unauthenticated(client, adult):
    conversation_id = await _conversation(client, adult)
    response = await client.post(f"/conversations/{conversation_id}/messages", json=QUESTION)
    _assert_error(response, 401, "unauthenticated")


async def test_age_not_confirmed(client, user):
    conversation_id = await _conversation(client, user)
    _assert_error(await _ask(client, user, conversation_id), 403, "age_not_confirmed")


async def test_on_break_returns_end_of_break(client, adult):
    conversation_id = await _conversation(client, adult)
    await client.post("/me/break", headers=adult.headers, json={"duration": "7d"})

    response = await _ask(client, adult, conversation_id)

    _assert_error(response, 403, "on_break")
    assert response.json()["error"]["retry_at"] == "2026-10-17T11:00:00Z"


async def test_break_over_allows_chat(client, clock, adult):
    conversation_id = await _conversation(client, adult)
    await client.post("/me/break", headers=adult.headers, json={"duration": "24h"})
    clock.now = NOW + timedelta(hours=24, seconds=1)

    response = await _ask(client, adult, conversation_id)

    assert response.status_code == 200


async def test_age_gate_comes_before_break(client, pool, user):
    conversation_id = await _conversation(client, user)
    await pool.execute(
        "UPDATE profiles SET self_excluded_until = $2 WHERE id = $1",
        user.id,
        NOW + timedelta(days=1),
    )
    _assert_error(await _ask(client, user, conversation_id), 403, "age_not_confirmed")


async def test_per_ip_rate_limit(client, settings, adult):
    conversation_id = await _conversation(client, adult)
    for _ in range(settings.per_ip_requests_per_minute):
        assert (await _ask(client, adult, conversation_id)).status_code == 200

    response = await _ask(client, adult, conversation_id)

    _assert_error(response, 429, "rate_limited")
    assert response.json()["error"]["retry_at"] == "2026-10-10T11:01:00Z"


async def test_rate_limit_is_per_ip(deps, make_client, adult, settings):
    async with (
        make_client(deps, ip="198.51.100.1") as first,
        make_client(deps, ip="198.51.100.2") as second,
    ):
        conversation_id = await _conversation(first, adult)
        for _ in range(settings.per_ip_requests_per_minute):
            await _ask(first, adult, conversation_id)

        assert (await _ask(second, adult, conversation_id)).status_code == 200


async def test_rate_limit_resets_next_minute(client, clock, settings, adult):
    conversation_id = await _conversation(client, adult)
    for _ in range(settings.per_ip_requests_per_minute):
        await _ask(client, adult, conversation_id)
    clock.now = NOW + timedelta(minutes=1)

    assert (await _ask(client, adult, conversation_id)).status_code == 200


async def test_daily_question_limit(client, redis, adult):
    conversation_id = await _conversation(client, adult)
    await redis.set(f"questions:2026-10-10:{adult.id}", 15)

    response = await _ask(client, adult, conversation_id)

    _assert_error(response, 429, "daily_limit_reached")
    assert response.json()["error"]["retry_at"] == "2026-10-10T23:00:00Z"


async def test_daily_limit_resets_at_uk_midnight(client, redis, clock, adult):
    conversation_id = await _conversation(client, adult)
    await redis.set(f"questions:2026-10-10:{adult.id}", 15)
    clock.now = NOW.replace(hour=23, minute=0, second=1)  # 00:00:01 BST on the 11th

    assert (await _ask(client, adult, conversation_id)).status_code == 200


async def test_budget_exhausted(client, redis, adult):
    conversation_id = await _conversation(client, adult)
    await redis.set("tokens:2026-10-10", 100_000)

    response = await _ask(client, adult, conversation_id)

    _assert_error(response, 503, "budget_exhausted")
    assert "tomorrow" in response.json()["error"]["message"]


async def test_no_budget_configured_means_no_budget_gate(
    with_deps, make_client, settings, redis, adult
):
    no_budget = settings.model_copy(update={"daily_token_budget": None})
    await redis.set("tokens:2026-10-10", 10**12)
    async with make_client(with_deps(settings=no_budget)) as http:
        conversation_id = await _conversation(http, adult)
        assert (await _ask(http, adult, conversation_id)).status_code == 200


async def test_daily_limit_comes_before_budget(client, redis, adult):
    conversation_id = await _conversation(client, adult)
    await redis.set(f"questions:2026-10-10:{adult.id}", 15)
    await redis.set("tokens:2026-10-10", 100_000)

    _assert_error(await _ask(client, adult, conversation_id), 429, "daily_limit_reached")


async def test_question_to_someone_elses_conversation_is_not_found(client, make_user, redis, adult):
    other = await make_user(email="other@example.com", age_confirmed=True)
    theirs = await _conversation(client, other)

    response = await _ask(client, adult, theirs)

    _assert_error(response, 404, "not_found")
    assert await redis.get(f"questions:2026-10-10:{adult.id}") is None


@pytest.mark.parametrize("body", [{"content": ""}, {"content": "x" * 1001}, {}])
async def test_question_length_is_validated(client, adult, body):
    conversation_id = await _conversation(client, adult)
    _assert_error(await _ask(client, adult, conversation_id, body), 422, "invalid_input")


async def test_whitespace_only_question_is_invalid(client, adult):
    conversation_id = await _conversation(client, adult)
    _assert_error(
        await _ask(client, adult, conversation_id, {"content": "   \n "}), 422, "invalid_input"
    )
