"""Shared HTTP behaviour for provider clients: retries, quota guard and quota logging."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from oddsmith_ingestion.providers.errors import QuotaExhausted, RetryableError

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_RETRY_WAIT_SECONDS = 2.0
MAX_RETRY_WAIT_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 30.0


class ProviderClient:
    """Base for one provider. Subclasses set the class attributes and implement `_check`."""

    name: str
    base_url: str
    remaining_header: str

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_wait: float = DEFAULT_RETRY_WAIT_SECONDS,
        quota_reserve: int = 0,
        min_interval: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ValueError(f"{self.name}: API key is empty")
        self._http = http
        self._api_key = api_key
        self._max_attempts = max_attempts
        self._retry_wait = retry_wait
        self._quota_reserve = quota_reserve
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_sent_at: float | None = None
        self.quota_remaining: int | None = None

    def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return (headers, params) that authenticate a request."""
        raise NotImplementedError

    def _check(self, response: httpx.Response) -> None:
        """Raise RetryableError, QuotaExhausted or ProviderError for a failed response."""
        raise NotImplementedError

    async def _request(self, path: str, params: dict[str, Any]) -> httpx.Response:
        self._guard_quota()
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=self._retry_wait, max=MAX_RETRY_WAIT_SECONDS),
            retry=retry_if_exception_type(RetryableError),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                response = await self._send(path, params)
                self._record_quota(response)
                self._check(response)
                return response
        raise AssertionError("unreachable")  # pragma: no cover

    async def _send(self, path: str, params: dict[str, Any]) -> httpx.Response:
        await self._throttle()
        headers, auth_params = self._auth()
        try:
            return await self._http.get(
                f"{self.base_url}/{path}",
                params={**params, **auth_params},
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.TransportError as exc:
            raise RetryableError(f"{self.name} {path}: {exc!r}") from exc

    async def _throttle(self) -> None:
        """Keep at least `min_interval` seconds between requests (per-minute plan limits)."""
        if self._last_sent_at is not None:
            wait = self._min_interval - (self._clock() - self._last_sent_at)
            if wait > 0:
                await self._sleep(wait)
        self._last_sent_at = self._clock()

    def _guard_quota(self) -> None:
        if self.quota_remaining is not None and self.quota_remaining <= self._quota_reserve:
            raise QuotaExhausted(
                f"{self.name}: {self.quota_remaining} left, reserve is {self._quota_reserve}"
            )

    def _record_quota(self, response: httpx.Response) -> None:
        raw = response.headers.get(self.remaining_header)
        if raw is None:
            return
        try:
            self.quota_remaining = int(float(raw))
        except ValueError:
            logger.warning("%s: unparseable %s header %r", self.name, self.remaining_header, raw)
            return
        logger.info(
            "%s %s -> %s, quota remaining %s",
            self.name,
            response.request.url.path,
            response.status_code,
            self.quota_remaining,
        )


def is_transient(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500
