"""The Odds API v4 client (match odds). Cost per call = markets x regions;
every 10 bookmakers passed via `bookmakers=` count as one region."""

from typing import Any

import httpx

from oddsmith_ingestion.providers.base import ProviderClient, is_transient
from oddsmith_ingestion.providers.errors import ProviderError, QuotaExhausted, RetryableError

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "soccer_epl"
OUT_OF_CREDITS = "OUT_OF_USAGE_CREDITS"


class OddsApiClient(ProviderClient):
    name = "the-odds-api"
    base_url = BASE_URL
    remaining_header = "x-requests-remaining"

    def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        return {}, {"apiKey": self._api_key}

    def _check(self, response: httpx.Response) -> None:
        if is_transient(response.status_code):
            raise RetryableError(f"{self.name}: HTTP {response.status_code}")
        if response.status_code < 400:
            return
        detail = _error_body(response)
        if detail.get("error_code") == OUT_OF_CREDITS:
            raise QuotaExhausted(f"{self.name}: {detail.get('message')}")
        raise ProviderError(
            f"{self.name}: HTTP {response.status_code} {detail.get('message', '')}".strip()
        )

    async def events(self) -> list[dict[str, Any]]:
        """Upcoming events with ids. Costs no credits."""
        return (await self._request(f"sports/{SPORT}/events", {})).json()

    async def odds(self, *, markets: list[str], bookmakers: list[str]) -> list[dict[str, Any]]:
        """Featured markets (h2h, totals) for every upcoming event."""
        return (
            await self._request(f"sports/{SPORT}/odds", _odds_params(markets, bookmakers))
        ).json()

    async def event_odds(
        self, event_id: str, *, markets: list[str], bookmakers: list[str]
    ) -> dict[str, Any]:
        """Any market (incl. btts) for one event."""
        path = f"sports/{SPORT}/events/{event_id}/odds"
        return (await self._request(path, _odds_params(markets, bookmakers))).json()


def _odds_params(markets: list[str], bookmakers: list[str]) -> dict[str, str]:
    return {
        "markets": ",".join(markets),
        "bookmakers": ",".join(bookmakers),
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }


def _error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {"message": response.text[:200]}
    return body if isinstance(body, dict) else {}
