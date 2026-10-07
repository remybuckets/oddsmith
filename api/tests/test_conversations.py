import uuid

import pytest


async def _create(client, user, count=1):
    ids = []
    for _ in range(count):
        response = await client.post("/conversations", headers=user.headers)
        ids.append(response.json()["data"]["id"])
    return ids


async def test_create_conversation(client, adult):
    response = await client.post("/conversations", headers=adult.headers)

    assert response.status_code == 201
    data = response.json()["data"]
    assert uuid.UUID(data["id"])
    assert data["title"] is None
    assert data["created_at"].endswith("Z")
    assert data["updated_at"].endswith("Z")


async def test_list_is_newest_first_and_only_mine(client, make_user, adult):
    other = await make_user(email="other@example.com", age_confirmed=True)
    mine = await _create(client, adult, 3)
    await _create(client, other, 2)

    response = await client.get("/conversations", headers=adult.headers)

    assert response.status_code == 200
    body = response.json()
    assert [c["id"] for c in body["data"]] == list(reversed(mine))
    assert body["meta"] == {"next_cursor": None}


async def test_list_paginates_with_cursor(client, adult):
    mine = list(reversed(await _create(client, adult, 5)))

    first = (await client.get("/conversations?limit=2", headers=adult.headers)).json()
    cursor = first["meta"]["next_cursor"]
    second = (
        await client.get(f"/conversations?limit=2&cursor={cursor}", headers=adult.headers)
    ).json()
    cursor = second["meta"]["next_cursor"]
    third = (
        await client.get(f"/conversations?limit=2&cursor={cursor}", headers=adult.headers)
    ).json()

    pages = [c["id"] for page in (first, second, third) for c in page["data"]]
    assert pages == mine
    assert third["meta"]["next_cursor"] is None


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "cursor=not-a-cursor"])
async def test_list_rejects_bad_paging(client, adult, query):
    response = await client.get(f"/conversations?{query}", headers=adult.headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_messages_of_unknown_conversation_is_not_found(client, adult):
    response = await client.get(f"/conversations/{uuid.uuid4()}/messages", headers=adult.headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_cannot_read_someone_elses_messages(client, make_user, adult):
    other = await make_user(email="other@example.com", age_confirmed=True)
    [theirs] = await _create(client, other)

    response = await client.get(f"/conversations/{theirs}/messages", headers=adult.headers)

    assert response.status_code == 404


async def test_bad_conversation_id_is_invalid_input(client, adult):
    response = await client.get("/conversations/nope/messages", headers=adult.headers)

    assert response.status_code == 422


async def test_unknown_route_uses_envelope(client):
    response = await client.get("/nowhere")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
