from datetime import datetime, timedelta

import pytest

from tests.conftest import NOW


async def test_me_for_new_user(client, user):
    response = await client.get("/me", headers=user.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"] == {
        "id": str(user.id),
        "email": user.email,
        "age_confirmed": False,
        "self_excluded_until": None,
        "usage": {
            "questions_today": 0,
            "daily_limit": 15,
            "resets_at": "2026-10-10T23:00:00Z",
        },
    }


async def test_me_counts_questions_asked_today(client, redis, adult):
    await redis.set(f"questions:2026-10-10:{adult.id}", 4)

    response = await client.get("/me", headers=adult.headers)

    assert response.json()["data"]["usage"]["questions_today"] == 4


async def test_onboarding_records_age_and_terms(client, pool, user):
    response = await client.post(
        "/onboarding/age", headers=user.headers, json={"is_over_18": True, "accepts_terms": True}
    )

    assert response.status_code == 200
    assert response.json()["data"]["age_confirmed"] is True
    row = await pool.fetchrow(
        "SELECT age_confirmed_at, terms_accepted_at FROM profiles WHERE id = $1", user.id
    )
    assert row["age_confirmed_at"] is not None
    assert row["terms_accepted_at"] is not None


async def test_onboarding_twice_keeps_first_timestamp(client, pool, user):
    body = {"is_over_18": True, "accepts_terms": True}
    await client.post("/onboarding/age", headers=user.headers, json=body)
    first = await pool.fetchval("SELECT age_confirmed_at FROM profiles WHERE id = $1", user.id)

    await client.post("/onboarding/age", headers=user.headers, json=body)

    assert (
        await pool.fetchval("SELECT age_confirmed_at FROM profiles WHERE id = $1", user.id) == first
    )


@pytest.mark.parametrize(
    "body",
    [
        {"is_over_18": False, "accepts_terms": True},
        {"is_over_18": True, "accepts_terms": False},
        {"is_over_18": True},
        {},
    ],
)
async def test_onboarding_requires_both_declarations(client, user, body):
    response = await client.post("/onboarding/age", headers=user.headers, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


@pytest.mark.parametrize(
    ("duration", "expected"),
    [("24h", timedelta(hours=24)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30))],
)
async def test_break_sets_exclusion(client, adult, duration, expected):
    response = await client.post("/me/break", headers=adult.headers, json={"duration": duration})

    assert response.status_code == 200
    until = datetime.fromisoformat(response.json()["data"]["self_excluded_until"])
    assert until == NOW + expected


async def test_break_cannot_be_shortened(client, adult):
    await client.post("/me/break", headers=adult.headers, json={"duration": "30d"})

    response = await client.post("/me/break", headers=adult.headers, json={"duration": "24h"})

    until = datetime.fromisoformat(response.json()["data"]["self_excluded_until"])
    assert until == NOW + timedelta(days=30)


async def test_break_can_be_extended(client, adult):
    await client.post("/me/break", headers=adult.headers, json={"duration": "24h"})

    response = await client.post("/me/break", headers=adult.headers, json={"duration": "7d"})

    until = datetime.fromisoformat(response.json()["data"]["self_excluded_until"])
    assert until == NOW + timedelta(days=7)


async def test_expired_break_shows_as_none(client, pool, adult):
    await client.get("/me", headers=adult.headers)
    await pool.execute(
        "UPDATE profiles SET self_excluded_until = $2 WHERE id = $1",
        adult.id,
        NOW - timedelta(minutes=1),
    )

    response = await client.get("/me", headers=adult.headers)

    assert response.json()["data"]["self_excluded_until"] is None


async def test_break_rejects_unknown_duration(client, adult):
    response = await client.post("/me/break", headers=adult.headers, json={"duration": "1h"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_delete_me_removes_user_and_all_their_data(client, pool, admin, adult):
    created = await client.post("/conversations", headers=adult.headers)
    assert created.status_code == 201

    response = await client.delete("/me", headers=adult.headers)

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": None, "error": None}
    assert admin.deleted == [adult.id]
    assert await pool.fetchval("SELECT count(*) FROM profiles WHERE id = $1", adult.id) == 0
    assert (
        await pool.fetchval("SELECT count(*) FROM conversations WHERE user_id = $1", adult.id) == 0
    )


async def test_delete_me_failure_returns_friendly_error(client, with_deps, make_client, adult):
    class BrokenAdmin:
        async def delete_user(self, user_id):
            raise RuntimeError("supabase down")

    async with make_client(with_deps(admin=BrokenAdmin())) as broken:
        response = await broken.delete("/me", headers=adult.headers)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal"
    assert "supabase" not in response.json()["error"]["message"].lower()
