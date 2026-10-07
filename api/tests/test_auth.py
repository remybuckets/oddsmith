import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import TokenVerifier
from app.envelope import ApiError
from tests.conftest import ISSUER


async def _get_me(client, headers):
    return await client.get("/me", headers=headers)


def _assert_unauthenticated(response):
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "unauthenticated"


async def test_missing_token_is_rejected(client):
    _assert_unauthenticated(await _get_me(client, {}))


async def test_non_bearer_scheme_is_rejected(client, user):
    token = user.headers["Authorization"].removeprefix("Bearer ")
    _assert_unauthenticated(await _get_me(client, {"Authorization": f"Basic {token}"}))


@pytest.mark.parametrize(
    "token_args",
    [
        {"expires_in": -60},
        {"issuer": "http://evil.test/auth/v1"},
        {"audience": "anon"},
    ],
    ids=["expired", "wrong-issuer", "wrong-audience"],
)
async def test_invalid_claims_are_rejected(client, user, make_token, token_args):
    token = make_token(user.id, **token_args)
    _assert_unauthenticated(await _get_me(client, {"Authorization": f"Bearer {token}"}))


async def test_token_signed_by_another_key_is_rejected(client, user, make_token):
    token = make_token(user.id, key=ec.generate_private_key(ec.SECP256R1()))
    _assert_unauthenticated(await _get_me(client, {"Authorization": f"Bearer {token}"}))


async def test_garbage_token_is_rejected(client):
    _assert_unauthenticated(await _get_me(client, {"Authorization": "Bearer not.a.jwt"}))


async def test_token_for_deleted_user_is_rejected(client, make_token):
    token = make_token(uuid.uuid4())  # no auth.users row
    _assert_unauthenticated(await _get_me(client, {"Authorization": f"Bearer {token}"}))


async def test_first_request_creates_profile(client, pool, user):
    assert await pool.fetchval("SELECT count(*) FROM profiles WHERE id = $1", user.id) == 0

    response = await _get_me(client, user.headers)

    assert response.status_code == 200
    assert await pool.fetchval("SELECT count(*) FROM profiles WHERE id = $1", user.id) == 1


async def test_repeat_requests_keep_one_profile(client, pool, user):
    await _get_me(client, user.headers)
    await _get_me(client, user.headers)
    assert await pool.fetchval("SELECT count(*) FROM profiles WHERE id = $1", user.id) == 1


def test_verifier_rejects_token_without_subject(signing_key):
    import jwt

    token = jwt.encode(
        {"aud": "authenticated", "iss": ISSUER, "exp": 9_999_999_999},
        signing_key,
        algorithm="ES256",
    )
    verifier = TokenVerifier(lambda _t: signing_key.public_key(), issuer=ISSUER)
    with pytest.raises(ApiError) as caught:
        verifier.verify(token)
    assert caught.value.code == "unauthenticated"


def test_verifier_rejects_non_uuid_subject(signing_key):
    import jwt

    token = jwt.encode(
        {"sub": "nope", "aud": "authenticated", "iss": ISSUER, "exp": 9_999_999_999},
        signing_key,
        algorithm="ES256",
    )
    verifier = TokenVerifier(lambda _t: signing_key.public_key(), issuer=ISSUER)
    with pytest.raises(ApiError):
        verifier.verify(token)
