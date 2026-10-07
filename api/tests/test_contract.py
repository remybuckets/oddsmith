"""Every route, success and error, checked against contracts/openapi.yaml."""

from datetime import timedelta

import pytest

from app.main import create_app
from tests.conftest import NOW
from tests.contract import assert_conforms, assert_response, contract_operations
from tests.sse import parse_sse

MESSAGES = "/conversations/{id}/messages"


def test_routes_match_contract_exactly(deps):
    generated = create_app(deps).openapi()["paths"]
    served = {
        (path.replace("{conversation_id}", "{id}"), method)
        for path, operations in generated.items()
        for method in operations
    }
    assert served == contract_operations()


async def test_framework_docs_are_not_served(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client.get(path)).status_code == 404


async def _conversation(client, user) -> str:
    response = await client.post("/conversations", headers=user.headers)
    assert_response(response, "/conversations", "post")
    return response.json()["data"]["id"]


async def _seed_fixture(pool):
    home = await pool.fetchval(
        "INSERT INTO teams (provider_id, name, short_name) VALUES (1, 'Brentford', 'Brentford') "
        "RETURNING id"
    )
    away = await pool.fetchval(
        "INSERT INTO teams (provider_id, name, short_name) VALUES (2, 'Fulham', 'Fulham') "
        "RETURNING id"
    )
    await pool.execute(
        "INSERT INTO fixtures (provider_id, season, matchweek, home_id, away_id, kickoff_at, "
        "status) VALUES (9, '2026/27', 6, $1, $2, $3, 'scheduled')",
        home,
        away,
        NOW + timedelta(hours=2),
    )


async def test_profile_routes_conform(client, user):
    assert_response(await client.get("/me", headers=user.headers), "/me", "get")
    assert_response(
        await client.post(
            "/onboarding/age",
            headers=user.headers,
            json={"is_over_18": True, "accepts_terms": True},
        ),
        "/onboarding/age",
        "post",
    )
    assert_response(
        await client.post("/me/break", headers=user.headers, json={"duration": "24h"}),
        "/me/break",
        "post",
    )
    assert_response(await client.delete("/me", headers=user.headers), "/me", "delete")


async def test_conversation_routes_conform(client, adult):
    conversation_id = await _conversation(client, adult)
    await _conversation(client, adult)
    first = await client.get("/conversations?limit=1", headers=adult.headers)
    assert_response(first, "/conversations", "get")
    cursor = first.json()["meta"]["next_cursor"]
    assert_response(
        await client.get(f"/conversations?limit=1&cursor={cursor}", headers=adult.headers),
        "/conversations",
        "get",
    )

    streamed = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=adult.headers,
        json={"content": "Who's injured?"},
    )
    assert_response(streamed, MESSAGES, "post")

    listed = await client.get(f"/conversations/{conversation_id}/messages", headers=adult.headers)
    assert_response(listed, MESSAGES, "get")

    message_id = parse_sse(streamed.text)[0][1]["message_id"]
    assert_response(
        await client.post(
            "/feedback",
            headers=adult.headers,
            json={"message_id": message_id, "rating": -1, "note": "wrong"},
        ),
        "/feedback",
        "post",
    )
    after_feedback = await client.get(
        f"/conversations/{conversation_id}/messages", headers=adult.headers
    )
    assert_response(after_feedback, MESSAGES, "get")


async def test_public_routes_conform(client, pool):
    assert_response(await client.get("/health"), "/health", "get")
    assert_response(await client.get("/fixtures/next"), "/fixtures/next", "get")  # 404 envelope
    await _seed_fixture(pool)
    assert_response(await client.get("/fixtures/next"), "/fixtures/next", "get")


async def test_error_responses_conform(client, redis, make_user, adult):
    newcomer = await make_user(email="new@example.com")
    conversation_id = await _conversation(client, adult)
    url = f"/conversations/{conversation_id}/messages"
    question = {"content": "Is there value in Newcastle to win?"}

    assert_response(await client.get("/me"), "/me", "get")  # 401
    assert_response(
        await client.post(url, headers=newcomer.headers, json=question), MESSAGES, "post"
    )  # 403 age_not_confirmed
    assert_response(
        await client.post(url, headers=adult.headers, json={"content": ""}), MESSAGES, "post"
    )  # 422
    await redis.set("tokens:2026-10-10", 10**9)
    assert_response(
        await client.post(url, headers=adult.headers, json=question), MESSAGES, "post"
    )  # 503
    await redis.set(f"questions:2026-10-10:{adult.id}", 15)
    assert_response(
        await client.post(url, headers=adult.headers, json=question), MESSAGES, "post"
    )  # 429 daily_limit_reached
    await client.post("/me/break", headers=adult.headers, json={"duration": "7d"})
    assert_response(
        await client.post(url, headers=adult.headers, json=question), MESSAGES, "post"
    )  # 403 on_break


@pytest.mark.parametrize(
    "event",
    [
        {"type": "error", "error": {"code": "internal", "message": "x", "retry_at": None}},
        {"type": "sources", "sources": []},
    ],
)
def test_backend_generated_events_conform(event):
    assert_conforms(event, "/components/schemas/StreamEvent")


def test_contract_helper_catches_a_bad_payload():
    with pytest.raises(AssertionError, match="questions_today"):
        assert_conforms(
            {
                "success": True,
                "error": None,
                "data": {
                    "id": "6f1c2a7e-0000-4000-8000-000000000000",
                    "email": "a@b.co",
                    "age_confirmed": True,
                    "self_excluded_until": None,
                    "usage": {"daily_limit": 15, "resets_at": "2026-10-10T23:00:00Z"},
                },
            },
            "/components/responses/Me/content/application~1json/schema",
        )
