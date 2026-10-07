import uuid

from tests.sse import parse_sse


async def _answered(client, user) -> str:
    conversation_id = (await client.post("/conversations", headers=user.headers)).json()["data"][
        "id"
    ]
    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=user.headers,
        json={"content": "Who's injured?"},
    )
    return parse_sse(response.text)[0][1]["message_id"]


async def test_feedback_is_recorded_and_shown(client, pool, adult):
    message_id = await _answered(client, adult)

    response = await client.post(
        "/feedback",
        headers=adult.headers,
        json={"message_id": message_id, "rating": 1, "note": "spot on"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": None, "error": None}
    row = await pool.fetchrow("SELECT rating, note FROM feedback WHERE user_id = $1", adult.id)
    assert dict(row) == {"rating": 1, "note": "spot on"}


async def test_feedback_repost_replaces_rating(client, pool, adult):
    message_id = await _answered(client, adult)
    await client.post(
        "/feedback",
        headers=adult.headers,
        json={"message_id": message_id, "rating": 1, "note": "good"},
    )

    await client.post(
        "/feedback", headers=adult.headers, json={"message_id": message_id, "rating": -1}
    )

    rows = await pool.fetch("SELECT rating, note FROM feedback WHERE user_id = $1", adult.id)
    assert [dict(r) for r in rows] == [{"rating": -1, "note": None}]
    conversation_messages = await client.get(
        f"/conversations/{await _conversation_of(pool, message_id)}/messages",
        headers=adult.headers,
    )
    assert conversation_messages.json()["data"][1]["feedback"] == -1


async def _conversation_of(pool, message_id):
    return await pool.fetchval(
        "SELECT conversation_id FROM messages WHERE id = $1", uuid.UUID(message_id)
    )


async def test_feedback_on_someone_elses_message_is_not_found(client, make_user, adult):
    other = await make_user(email="other@example.com", age_confirmed=True)
    message_id = await _answered(client, other)

    response = await client.post(
        "/feedback", headers=adult.headers, json={"message_id": message_id, "rating": 1}
    )

    assert response.status_code == 404


async def test_feedback_on_own_question_is_not_found(client, pool, adult):
    message_id = await _answered(client, adult)
    user_message = await pool.fetchval(
        "SELECT id FROM messages WHERE role = 'user' AND conversation_id = $1",
        await _conversation_of(pool, message_id),
    )

    response = await client.post(
        "/feedback", headers=adult.headers, json={"message_id": str(user_message), "rating": 1}
    )

    assert response.status_code == 404


async def test_feedback_validates_rating_and_note(client, adult):
    message_id = await _answered(client, adult)
    for body in (
        {"message_id": message_id, "rating": 0},
        {"message_id": message_id, "rating": 1, "note": "x" * 1001},
    ):
        response = await client.post("/feedback", headers=adult.headers, json=body)
        assert response.status_code == 422
