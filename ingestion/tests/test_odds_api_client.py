import httpx
import pytest
import respx

from oddsmith_ingestion.providers.errors import ProviderError, QuotaExhausted
from oddsmith_ingestion.providers.odds_api import BASE_URL, SPORT, OddsApiClient

ODDS_URL = f"{BASE_URL}/sports/{SPORT}/odds"
CREDIT_HEADERS = {"x-requests-remaining": "480", "x-requests-used": "20", "x-requests-last": "2"}


def make_client(http, **kwargs):
    return OddsApiClient(http, api_key="test-key", retry_wait=0, **kwargs)


@respx.mock
async def test_odds_passes_bookmakers_not_regions_and_tracks_credits():
    # Arrange
    route = respx.get(ODDS_URL).mock(
        return_value=httpx.Response(200, json=[{"id": "evt"}], headers=CREDIT_HEADERS)
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        # Act
        result = await client.odds(markets=["h2h", "totals"], bookmakers=["skybet", "coral"])
    # Assert
    assert result == [{"id": "evt"}]
    params = route.calls.last.request.url.params
    assert params["apiKey"] == "test-key"
    assert params["markets"] == "h2h,totals"
    assert params["bookmakers"] == "skybet,coral"
    assert params["oddsFormat"] == "decimal"
    assert "regions" not in params
    assert client.quota_remaining == 480


@respx.mock
async def test_out_of_credits_raises_quota_exhausted():
    respx.get(ODDS_URL).mock(
        return_value=httpx.Response(
            401,
            json={"message": "Usage quota has been reached", "error_code": "OUT_OF_USAGE_CREDITS"},
        )
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(QuotaExhausted):
            await make_client(http).odds(markets=["h2h"], bookmakers=["skybet"])


@respx.mock
async def test_invalid_params_raise_provider_error_without_retry():
    route = respx.get(ODDS_URL).mock(
        return_value=httpx.Response(
            422, json={"message": "Invalid markets", "error_code": "INVALID"}
        )
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError, match="Invalid markets"):
            await make_client(http, max_attempts=3).odds(markets=["nope"], bookmakers=["skybet"])
    assert route.call_count == 1


@respx.mock
async def test_retries_429_then_succeeds():
    route = respx.get(ODDS_URL).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=[])]
    )
    async with httpx.AsyncClient() as http:
        await make_client(http, max_attempts=2).odds(markets=["h2h"], bookmakers=["skybet"])
    assert route.call_count == 2


@respx.mock
async def test_refuses_to_call_below_reserve():
    route = respx.get(ODDS_URL).mock(
        return_value=httpx.Response(200, json=[], headers={"x-requests-remaining": "10"})
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http, quota_reserve=10)
        await client.odds(markets=["h2h"], bookmakers=["skybet"])
        with pytest.raises(QuotaExhausted):
            await client.odds(markets=["h2h"], bookmakers=["skybet"])
    assert route.call_count == 1


@respx.mock
async def test_event_odds_hits_per_event_endpoint():
    route = respx.get(f"{BASE_URL}/sports/{SPORT}/events/abc/odds").mock(
        return_value=httpx.Response(200, json={"id": "abc", "bookmakers": []})
    )
    async with httpx.AsyncClient() as http:
        result = await make_client(http).event_odds("abc", markets=["btts"], bookmakers=["skybet"])
    assert result["id"] == "abc"
    assert route.calls.last.request.url.params["markets"] == "btts"


@respx.mock
async def test_events_lists_upcoming_events():
    respx.get(f"{BASE_URL}/sports/{SPORT}/events").mock(
        return_value=httpx.Response(200, json=[{"id": "abc"}])
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).events() == [{"id": "abc"}]
