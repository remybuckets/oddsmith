"""Supabase access-token verification. Supabase signs with asymmetric keys published as a JWKS."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt

from app.envelope import internal, unauthenticated

logger = logging.getLogger(__name__)

SUPABASE_AUDIENCE = "authenticated"
ALLOWED_ALGORITHMS = ["ES256", "RS256"]

KeyResolver = Callable[[str], Any]


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    email: str


class TokenVerifier:
    def __init__(
        self, key_resolver: KeyResolver, issuer: str, audience: str = SUPABASE_AUDIENCE
    ) -> None:
        self._key_resolver = key_resolver
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> AuthUser:
        """Blocking on a JWKS cache miss, so call it from a worker thread."""
        try:
            claims = jwt.decode(
                token,
                self._key_resolver(token),
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            return AuthUser(id=uuid.UUID(claims["sub"]), email=claims.get("email", ""))
        except jwt.PyJWKClientConnectionError as exc:
            logger.error("could not fetch Supabase signing keys: %s", exc)
            raise internal() from exc
        except (jwt.PyJWTError, ValueError) as exc:
            logger.info("rejected access token: %s", exc)
            raise unauthenticated() from exc


def jwks_verifier(jwks_url: str, issuer: str) -> TokenVerifier:
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return TokenVerifier(lambda token: client.get_signing_key_from_jwt(token).key, issuer=issuer)
