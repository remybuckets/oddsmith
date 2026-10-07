"""sync_odds and sync_btts: append-only snapshots of pre-match odds from The Odds API.

sync_odds: h2h and totals for every upcoming match in one call (2 credits).
sync_btts: BTTS is only sold per event (1 credit each), so it is a separate, less frequent
job covering matches kicking off within BTTS_HORIZON; events are listed for free.
Bookmakers are the enabled rows of the `bookmakers` table. In-play prices are never stored.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import asyncpg

from oddsmith_ingestion import mapping
from oddsmith_ingestion.job_runs import run_job

logger = logging.getLogger(__name__)

JOB_NAME = "sync_odds"
BTTS_JOB_NAME = "sync_btts"
PROVIDER = "the-odds-api"
FEATURED_MARKETS = ["h2h", "totals"]
BTTS_HORIZON = timedelta(hours=48)
# odds_snapshots.price is numeric(7,3) with price > 1.
MIN_PRICE, MAX_PRICE = Decimal("1"), Decimal("9999.999")
# An event matches a fixture with the same teams kicking off within this tolerance.
KICKOFF_TOLERANCE = timedelta(hours=12)


class OddsSource(Protocol):
    async def events(self) -> list[dict[str, Any]]: ...
    async def odds(self, *, markets: list[str], bookmakers: list[str]) -> list[dict[str, Any]]: ...
    async def event_odds(
        self, event_id: str, *, markets: list[str], bookmakers: list[str]
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OddsRow:
    fixture_id: int
    market: str
    line: Decimal | None
    selection: str
    bookmaker: str
    price: Decimal


def build_odds_rows(event: dict[str, Any], fixture_id: int, bookmakers: set[str]) -> list[OddsRow]:
    """Every price in an event; unknown bookmakers, markets or outcomes are skipped."""
    rows = []
    for book in event.get("bookmakers", []):
        if book["key"] not in bookmakers:
            continue
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                try:
                    selection = mapping.odds_selection(
                        market["key"],
                        outcome["name"],
                        home=event["home_team"],
                        away=event["away_team"],
                    )
                except ValueError as exc:
                    logger.warning("skipping outcome: %s", exc)
                    continue
                price = Decimal(str(outcome["price"]))
                if not MIN_PRICE < price <= MAX_PRICE:
                    logger.warning("skipping price %s for %s %s", price, book["key"], selection)
                    continue
                line = outcome.get("point") if market["key"] == "totals" else None
                rows.append(
                    OddsRow(
                        fixture_id,
                        market["key"],
                        Decimal(str(line)) if line is not None else None,
                        selection,
                        book["key"],
                        Decimal(str(outcome["price"])),
                    )
                )
    return rows


async def enabled_bookmakers(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT key FROM bookmakers WHERE is_enabled AND provider = $1 ORDER BY sort_order, key",
        PROVIDER,
    )
    return [r["key"] for r in rows]


async def match_fixture(conn: asyncpg.Connection, event: dict[str, Any]) -> int | None:
    """The fixture for an Odds API event, via team aliases and kick-off time."""
    return await conn.fetchval(
        """WITH home AS (SELECT entity_id FROM entity_aliases
                         WHERE entity_type = 'team' AND alias_search = $1),
                away AS (SELECT entity_id FROM entity_aliases
                         WHERE entity_type = 'team' AND alias_search = $2)
           SELECT f.id FROM fixtures f
           WHERE (SELECT count(*) FROM home) = 1 AND (SELECT count(*) FROM away) = 1
             AND f.home_id = (SELECT entity_id FROM home)
             AND f.away_id = (SELECT entity_id FROM away)
             AND f.kickoff_at BETWEEN $3::timestamptz - $4::interval
                                  AND $3::timestamptz + $4::interval
           ORDER BY abs(extract(epoch FROM f.kickoff_at - $3::timestamptz)) LIMIT 1""",
        mapping.alias_search(event["home_team"]),
        mapping.alias_search(event["away_team"]),
        datetime.fromisoformat(event["commence_time"]),
        KICKOFF_TOLERANCE,
    )


async def insert_snapshots(
    conn: asyncpg.Connection, rows: list[OddsRow], captured_at: datetime
) -> int:
    """Append-only: a repeat of the same capture is ignored. Returns rows inserted."""
    inserted = await conn.fetchval(
        """WITH new AS (
             INSERT INTO odds_snapshots (fixture_id, market, line, selection, bookmaker, price,
                                         captured_at)
             SELECT * FROM unnest($1::bigint[], $2::text[], $3::numeric[], $4::text[],
                                  $5::text[], $6::numeric[], $7::timestamptz[])
             ON CONFLICT DO NOTHING RETURNING 1)
           SELECT count(*) FROM new""",
        [r.fixture_id for r in rows],
        [r.market for r in rows],
        [r.line for r in rows],
        [r.selection for r in rows],
        [r.bookmaker for r in rows],
        [r.price for r in rows],
        [captured_at] * len(rows),
    )
    return int(inserted)


async def sync_odds(pool: asyncpg.Pool, client: OddsSource, *, now: datetime | None = None) -> int:
    at = now or datetime.now(UTC)

    async def work() -> int:
        async with pool.acquire() as conn:
            bookmakers = await enabled_bookmakers(conn)
            events = await client.odds(markets=FEATURED_MARKETS, bookmakers=bookmakers)
            pairs = await _matched_pre_match(conn, events, at)
        rows = [r for e, fid in pairs for r in build_odds_rows(e, fid, set(bookmakers))]
        async with pool.acquire() as conn, conn.transaction():
            return await insert_snapshots(conn, rows, at)

    return await run_job(pool, JOB_NAME, work)


async def sync_btts(pool: asyncpg.Pool, client: OddsSource, *, now: datetime | None = None) -> int:
    at = now or datetime.now(UTC)

    async def work() -> int:
        async with pool.acquire() as conn:
            bookmakers = await enabled_bookmakers(conn)
            events = [
                e
                for e in await client.events()
                if datetime.fromisoformat(e["commence_time"]) <= at + BTTS_HORIZON
            ]
            pairs = await _matched_pre_match(conn, events, at)
        written = 0
        for event, fid in pairs:  # saved per event: each costs a credit, so keep what's paid for
            priced = await client.event_odds(event["id"], markets=["btts"], bookmakers=bookmakers)
            async with pool.acquire() as conn:
                written += await insert_snapshots(
                    conn, build_odds_rows(priced, fid, set(bookmakers)), at
                )
        return written

    return await run_job(pool, BTTS_JOB_NAME, work)


async def _matched_pre_match(
    conn: asyncpg.Connection, events: list[dict[str, Any]], at: datetime
) -> list[tuple[dict[str, Any], int]]:
    """Events not yet kicked off, paired with their fixture; unmatched ones are logged."""
    upcoming = [e for e in events if datetime.fromisoformat(e["commence_time"]) > at]
    matched = [(e, await match_fixture(conn, e)) for e in upcoming]
    unmatched = [f"{e['home_team']} v {e['away_team']}" for e, fid in matched if fid is None]
    if unmatched:
        logger.warning("%s odds events with no fixture: %s", len(unmatched), unmatched)
    return [(e, fid) for e, fid in matched if fid is not None]
