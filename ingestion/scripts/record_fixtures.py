"""Record one real response per provider endpoint into tests/fixtures/.

Spends API-Football requests and Odds API credits, so it runs only with --yes.
Usage: uv run python scripts/record_fixtures.py [--yes]
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from oddsmith_ingestion.providers.api_football import ApiFootballClient
from oddsmith_ingestion.providers.odds_api import OddsApiClient
from oddsmith_ingestion.settings import load_settings

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SAMPLE_TEAM_ID = 42  # Arsenal
PLAN = """Will spend (files already recorded are skipped):
  API-Football: up to 8 requests (teams, squad, team players page, season fixtures,
                one fixture's team stats and player stats, injuries x2)
  The Odds API: ~3 credits (events: 0, odds h2h+totals: 2, one event's btts: 1)"""


def fixture_path(provider: str, name: str) -> Path:
    return FIXTURES_DIR / provider / f"{name}.json"


def save(provider: str, name: str, payload: Any) -> None:
    path = fixture_path(provider, name)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(f"  wrote {path.relative_to(FIXTURES_DIR.parent.parent)}")


async def enabled_bookmakers(database_url: str) -> list[str]:
    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            "SELECT key FROM bookmakers WHERE is_enabled AND provider = 'the-odds-api' "
            "ORDER BY sort_order"
        )
    finally:
        await conn.close()
    return [r["key"] for r in rows]


async def record_api_football(http: httpx.AsyncClient, key: str, season: int) -> None:
    client = ApiFootballClient(http, api_key=key)

    async def record(name: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Save the full envelope; reuse an existing recording instead of spending quota."""
        if fixture_path("api_football", name).exists():
            return json.loads(fixture_path("api_football", name).read_text())
        body = (await client._request(path, params)).json()
        save("api_football", name, body)
        return body

    await record("teams", "teams", {"league": 39, "season": season})
    await record("squad", "players/squads", {"team": SAMPLE_TEAM_ID})
    await record(
        "players_team_page1", "players", {"team": SAMPLE_TEAM_ID, "season": season, "page": 1}
    )
    season_body = await record("fixtures_season", "fixtures", {"league": 39, "season": season})
    fixture_id = next(
        f["fixture"]["id"]
        for f in season_body["response"]
        if f["fixture"]["status"]["short"] == "FT"
    )
    await record("fixture_statistics", "fixtures/statistics", {"fixture": fixture_id})
    await record("fixture_players", "fixtures/players", {"fixture": fixture_id})
    await record("injuries_fixture", "injuries", {"fixture": fixture_id})
    await record(
        "injuries_team", "injuries", {"league": 39, "season": season, "team": SAMPLE_TEAM_ID}
    )
    print(f"  api-football quota remaining: {client.quota_remaining}")


async def record_odds_api(http: httpx.AsyncClient, key: str, bookmakers: list[str]) -> None:
    client = OddsApiClient(http, api_key=key)

    async def record(name: str, fetch) -> Any:
        if fixture_path("odds_api", name).exists():
            return json.loads(fixture_path("odds_api", name).read_text())
        payload = await fetch()
        save("odds_api", name, payload)
        return payload

    events = await record("events", client.events)
    await record(
        "odds_h2h_totals", lambda: client.odds(markets=["h2h", "totals"], bookmakers=bookmakers)
    )
    if events:
        await record(
            "event_odds_btts",
            lambda: client.event_odds(events[0]["id"], markets=["btts"], bookmakers=bookmakers),
        )
    print(f"  odds-api credits remaining: {client.quota_remaining}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="actually spend quota")
    args = parser.parse_args()
    print(PLAN)
    if not args.yes:
        print("Dry run. Re-run with --yes to record.")
        return
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    bookmakers = await enabled_bookmakers(settings.database_url)
    async with httpx.AsyncClient() as http:
        await record_api_football(http, settings.api_football_key, settings.api_football_season)
        await record_odds_api(http, settings.odds_api_key, bookmakers)


if __name__ == "__main__":
    asyncio.run(main())
