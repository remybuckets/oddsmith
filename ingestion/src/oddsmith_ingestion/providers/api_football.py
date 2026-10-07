"""API-Football v3 client (stats, fixtures, squads, injuries)."""

from typing import Any

import httpx

from oddsmith_ingestion.providers.base import ProviderClient, is_transient
from oddsmith_ingestion.providers.errors import ProviderError, QuotaExhausted, RetryableError

BASE_URL = "https://v3.football.api-sports.io"
PREMIER_LEAGUE_ID = 39
MAX_IDS_PER_REQUEST = 20


class ApiFootballClient(ProviderClient):
    name = "api-football"
    base_url = BASE_URL
    remaining_header = "x-ratelimit-requests-remaining"

    def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        return {"x-apisports-key": self._api_key}, {}

    def _check(self, response: httpx.Response) -> None:
        if is_transient(response.status_code):
            raise RetryableError(f"{self.name}: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {response.status_code}")
        # API-Football reports most failures as HTTP 200 with a non-empty `errors`.
        try:
            errors = response.json().get("errors") or {}
        except ValueError as exc:  # e.g. a gateway HTML page served with 200
            raise RetryableError(f"{self.name}: non-JSON response") from exc
        if not errors:
            return
        if isinstance(errors, dict) and "requests" in errors:
            raise QuotaExhausted(f"{self.name}: {errors['requests']}")
        if isinstance(errors, dict) and "rateLimit" in errors:
            raise RetryableError(f"{self.name}: {errors['rateLimit']}")
        raise ProviderError(f"{self.name}: {errors}")

    async def get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = await self._request(path, params)
        return response.json()["response"]

    async def get_all(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Follow `paging` and return every page's `response` items."""
        items: list[dict[str, Any]] = []
        page, total = 1, 1
        while page <= total:
            body = (await self._request(path, {**params, "page": page})).json()
            items = [*items, *body["response"]]
            total = body.get("paging", {}).get("total", 1)
            page += 1
        return items

    async def teams(self, season: int) -> list[dict[str, Any]]:
        return await self.get("teams", {"league": PREMIER_LEAGUE_ID, "season": season})

    async def squad(self, team_id: int) -> list[dict[str, Any]]:
        return await self.get("players/squads", {"team": team_id})

    async def fixtures(self, season: int) -> list[dict[str, Any]]:
        return await self.get("fixtures", {"league": PREMIER_LEAGUE_ID, "season": season})

    async def fixtures_by_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        """Up to 20 fixtures with events, lineups, team statistics and player stats."""
        if not 0 < len(ids) <= MAX_IDS_PER_REQUEST:
            raise ValueError(f"need 1-{MAX_IDS_PER_REQUEST} fixture ids, got {len(ids)}")
        return await self.get("fixtures", {"ids": "-".join(str(i) for i in ids)})

    async def injuries(self, season: int, **filters: Any) -> list[dict[str, Any]]:
        return await self.get(
            "injuries", {"league": PREMIER_LEAGUE_ID, "season": season, **filters}
        )
