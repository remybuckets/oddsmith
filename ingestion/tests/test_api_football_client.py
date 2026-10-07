import httpx
import pytest
import respx

from oddsmith_ingestion.providers.api_football import BASE_URL, ApiFootballClient
from oddsmith_ingestion.providers.errors import ProviderError, QuotaExhausted

QUOTA_HEADERS = {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "42"}


def body(response, *, errors=None, current=1, total=1):
    return {
        "get": "x",
        "errors": errors if errors is not None else [],
        "results": len(response),
        "paging": {"current": current, "total": total},
        "response": response,
    }


def make_client(http, **kwargs):
    return ApiFootballClient(http, api_key="test-key", retry_wait=0, **kwargs)


@respx.mock
async def test_get_sends_key_and_returns_response_list():
    # Arrange
    route = respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(200, json=body([{"team": {"id": 1}}]), headers=QUOTA_HEADERS)
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        # Act
        result = await client.get("teams", {"league": 39, "season": 2024})
    # Assert
    assert result == [{"team": {"id": 1}}]
    request = route.calls.last.request
    assert request.headers["x-apisports-key"] == "test-key"
    assert request.url.params["league"] == "39"
    assert client.quota_remaining == 42


@respx.mock
async def test_errors_in_200_body_raise_provider_error():
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200, json=body([], errors={"plan": "Free plans do not have access to this season"})
        )
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError, match="Free plans"):
            await make_client(http).get("teams", {"season": 2026})


@respx.mock
async def test_daily_request_limit_error_raises_quota_exhausted():
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200, json=body([], errors={"requests": "You have reached the request limit"})
        )
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(QuotaExhausted):
            await make_client(http).get("teams", {})


@respx.mock
async def test_retries_rate_limit_and_server_errors_then_succeeds():
    route = respx.get(f"{BASE_URL}/teams").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json=body([], errors={"rateLimit": "Too many requests"})),
            httpx.Response(503),
            httpx.Response(200, json=body([{"ok": True}])),
        ]
    )
    async with httpx.AsyncClient() as http:
        result = await make_client(http, max_attempts=4).get("teams", {})
    assert result == [{"ok": True}]
    assert route.call_count == 4


@respx.mock
async def test_gives_up_after_max_attempts():
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError):
            await make_client(http, max_attempts=2).get("teams", {})


@respx.mock
async def test_client_errors_are_not_retried():
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(403))
    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError, match="403"):
            await make_client(http, max_attempts=3).get("teams", {})
    assert route.call_count == 1


@respx.mock
async def test_refuses_to_call_when_quota_at_reserve():
    route = respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json=body([]),
            headers={"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "5"},
        )
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http, quota_reserve=5)
        await client.get("teams", {})
        with pytest.raises(QuotaExhausted):
            await client.get("teams", {})
    assert route.call_count == 1


@respx.mock
async def test_get_all_follows_paging():
    route = respx.get(f"{BASE_URL}/players").mock(
        side_effect=[
            httpx.Response(200, json=body([{"n": 1}], current=1, total=2)),
            httpx.Response(200, json=body([{"n": 2}], current=2, total=2)),
        ]
    )
    async with httpx.AsyncClient() as http:
        result = await make_client(http).get_all("players", {"team": 42})
    assert result == [{"n": 1}, {"n": 2}]
    assert route.calls[1].request.url.params["page"] == "2"


async def test_fixtures_by_ids_rejects_more_than_twenty():
    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError):
            await make_client(http).fixtures_by_ids(list(range(21)))


@respx.mock
async def test_fixtures_by_ids_joins_ids_with_dashes():
    route = respx.get(f"{BASE_URL}/fixtures").mock(return_value=httpx.Response(200, json=body([])))
    async with httpx.AsyncClient() as http:
        await make_client(http).fixtures_by_ids([10, 11, 12])
    assert route.calls.last.request.url.params["ids"] == "10-11-12"


@respx.mock
async def test_min_interval_spaces_out_requests():
    # Arrange: a fake clock that only moves when the client sleeps
    now = [100.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=body([])))
    async with httpx.AsyncClient() as http:
        client = make_client(http, min_interval=6.5, clock=lambda: now[0], sleep=fake_sleep)
        # Act
        await client.get("teams", {})
        now[0] += 1.5
        await client.get("teams", {})
    # Assert: first call is immediate, second waits out the rest of the gap
    assert sleeps == [pytest.approx(5.0)]


@respx.mock
async def test_non_json_200_is_retried():
    route = respx.get(f"{BASE_URL}/teams").mock(
        side_effect=[
            httpx.Response(200, text="<html>gateway</html>"),
            httpx.Response(200, json=body([{"ok": True}])),
        ]
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http, max_attempts=2).get("teams", {}) == [{"ok": True}]
    assert route.call_count == 2
