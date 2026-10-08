from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import load_fixture

from oddsmith_ingestion.jobs.sync_odds import sync_btts, sync_odds
from oddsmith_ingestion.repository import ensure_teams

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)  # BTTS horizon (48h) covers Saturday 10 Oct

# The Odds API name -> API-Football team (provider id, name); curated aliases link them.
TEAMS = {
    "Arsenal": (42, "Arsenal"),
    "Aston Villa": (66, "Aston Villa"),
    "Bournemouth": (35, "Bournemouth"),
    "Brentford": (55, "Brentford"),
    "Brighton and Hove Albion": (51, "Brighton"),
    "Chelsea": (49, "Chelsea"),
    "Coventry City": (1346, "Coventry"),
    "Crystal Palace": (52, "Crystal Palace"),
    "Everton": (45, "Everton"),
    "Fulham": (36, "Fulham"),
    "Hull City": (64, "Hull City"),
    "Ipswich Town": (57, "Ipswich"),
    "Leeds United": (63, "Leeds"),
    "Liverpool": (40, "Liverpool"),
    "Manchester City": (50, "Manchester City"),
    "Manchester United": (33, "Manchester United"),
    "Newcastle United": (34, "Newcastle"),
    "Nottingham Forest": (65, "Nottingham Forest"),
    "Sunderland": (746, "Sunderland"),
    "Tottenham Hotspur": (47, "Tottenham"),
}


def odds_events():
    return load_fixture("odds_api", "odds_h2h_totals")


def kickoff(event):
    return datetime.fromisoformat(event["commence_time"])


class FakeOdds:
    def __init__(self):
        self.odds_calls: list[dict] = []
        self.btts_calls: list[str] = []

    async def events(self):
        return [
            {k: e[k] for k in ("id", "commence_time", "home_team", "away_team")}
            for e in odds_events()
        ]

    async def odds(self, *, markets, bookmakers):
        self.odds_calls.append({"markets": markets, "bookmakers": bookmakers})
        return odds_events()

    async def event_odds(self, event_id, *, markets, bookmakers):
        assert markets == ["btts"]
        self.btts_calls.append(event_id)
        btts = load_fixture("odds_api", "event_odds_btts")
        return btts if event_id == btts["id"] else {**btts, "id": event_id, "bookmakers": []}


@pytest.fixture
async def fixtures(db):
    """A fixture row for every recorded odds event (provider ids are arbitrary here)."""
    async with db.acquire() as conn:
        ids = await ensure_teams(conn, [{"id": pid, "name": n} for pid, n in TEAMS.values()])
    for n, event in enumerate(odds_events(), start=1):
        await db.execute(
            """INSERT INTO fixtures (provider_id, season, home_id, away_id, kickoff_at, status)
               VALUES ($1, '2026/27', $2, $3, $4, 'scheduled')""",
            n,
            ids[TEAMS[event["home_team"]][0]],
            ids[TEAMS[event["away_team"]][0]],
            kickoff(event),
        )
    return db


def expected_featured_rows(events):
    return sum(len(m["outcomes"]) for e in events for b in e["bookmakers"] for m in b["markets"])


def btts_rows():
    btts = load_fixture("odds_api", "event_odds_btts")
    return sum(len(m["outcomes"]) for b in btts["bookmakers"] for m in b["markets"])


async def test_requests_enabled_bookmakers_in_sort_order(fixtures):
    client = FakeOdds()
    await fixtures.execute("UPDATE bookmakers SET is_enabled = false WHERE key = 'coral'")
    try:
        await sync_odds(fixtures, client, now=NOW)
    finally:  # bookmakers is seeded by the migration and not truncated between tests
        await fixtures.execute("UPDATE bookmakers SET is_enabled = true WHERE key = 'coral'")
    call = client.odds_calls[0]
    assert call["markets"] == ["h2h", "totals"]
    assert call["bookmakers"] == [
        "sport888",
        "betfair_sb_uk",
        "betfred_uk",
        "ladbrokes_uk",
        "paddypower",
        "skybet",
        "williamhill",
    ]


async def test_writes_every_price_with_mapped_selections(fixtures):
    rows = await sync_odds(fixtures, FakeOdds(), now=NOW)

    assert rows == expected_featured_rows(odds_events())
    arsenal = await fixtures.fetch(
        """SELECT o.* FROM odds_snapshots o JOIN fixtures f ON f.id = o.fixture_id
           JOIN teams h ON h.id = f.home_id WHERE h.name = 'Arsenal' AND o.bookmaker = 'betfred_uk'
           ORDER BY market, selection"""
    )
    h2h = {r["selection"]: r["price"] for r in arsenal if r["market"] == "h2h"}
    assert h2h == {"home": Decimal("1.36"), "away": Decimal("8.5"), "draw": Decimal("4.6")}
    assert all(r["captured_at"] == NOW for r in arsenal)
    lines = await fixtures.fetch("SELECT DISTINCT market, line FROM odds_snapshots")
    assert {(r["market"], r["line"]) for r in lines} == {("h2h", None), ("totals", 2.5)}
    run = await fixtures.fetchrow("SELECT * FROM job_runs WHERE name = 'sync_odds'")
    assert (run["status"], run["rows"]) == ("success", rows)


async def test_events_already_kicked_off_are_not_stored(fixtures):
    first_kickoff = min(kickoff(e) for e in odds_events())
    await sync_odds(fixtures, FakeOdds(), now=first_kickoff + timedelta(minutes=5))
    assert (
        await fixtures.fetchval(
            "SELECT count(*) FROM odds_snapshots o JOIN fixtures f ON f.id = o.fixture_id "
            "WHERE f.kickoff_at <= $1",
            first_kickoff,
        )
        == 0
    )


async def test_btts_only_for_matches_within_48_hours(fixtures):
    client = FakeOdds()
    rows = await sync_btts(fixtures, client, now=NOW)
    soon = {e["id"] for e in odds_events() if kickoff(e) <= NOW + timedelta(hours=48)}
    assert set(client.btts_calls) == soon
    assert 0 < len(soon) < len(odds_events())
    assert client.odds_calls == []
    assert rows == btts_rows()
    selections = await fixtures.fetch("SELECT DISTINCT market, selection FROM odds_snapshots")
    assert {(r["market"], r["selection"]) for r in selections} == {("btts", "yes"), ("btts", "no")}
    assert await fixtures.fetchval("SELECT status FROM job_runs WHERE name = 'sync_btts'") == (
        "success"
    )


async def test_is_append_only_and_idempotent_per_capture(fixtures):
    first = await sync_odds(fixtures, FakeOdds(), now=NOW)
    again = await sync_odds(fixtures, FakeOdds(), now=NOW)
    later = await sync_odds(fixtures, FakeOdds(), now=NOW + timedelta(hours=2))
    assert again == 0
    assert later == first
    assert await fixtures.fetchval("SELECT count(*) FROM odds_snapshots") == 2 * first


async def test_unmatched_events_are_skipped(fixtures):
    first = odds_events()[0]
    await fixtures.execute("DELETE FROM fixtures WHERE provider_id = 1")  # Arsenal v Leeds
    rows = await sync_odds(fixtures, FakeOdds(), now=NOW)
    assert rows == expected_featured_rows(odds_events()[1:])
    run = await fixtures.fetchrow("SELECT * FROM job_runs WHERE name = 'sync_odds'")
    assert run["status"] == "success"
    assert first["home_team"] == "Arsenal"


async def test_fixture_with_a_far_away_kickoff_does_not_match(fixtures):
    await fixtures.execute(
        "UPDATE fixtures SET kickoff_at = kickoff_at + interval '3 days' WHERE provider_id = 1"
    )
    await sync_odds(fixtures, FakeOdds(), now=NOW)
    assert (
        await fixtures.fetchval(
            "SELECT count(*) FROM odds_snapshots o JOIN fixtures f ON f.id = o.fixture_id "
            "WHERE f.provider_id = 1"
        )
        == 0
    )


def test_prices_the_schema_rejects_are_skipped():
    from oddsmith_ingestion.jobs.sync_odds import build_odds_rows

    event = {
        "home_team": "A",
        "away_team": "B",
        "bookmakers": [
            {
                "key": "skybet",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "A", "price": 1.0},
                            {"name": "B", "price": 3.2},
                            {"name": "Draw", "price": 12345.0},
                        ],
                    }
                ],
            }
        ],
    }
    assert [r.selection for r in build_odds_rows(event, 1, {"skybet"})] == ["away"]


async def test_btts_keeps_rows_already_paid_for_when_a_later_event_fails(fixtures):
    class FailsSecond(FakeOdds):
        async def event_odds(self, event_id, *, markets, bookmakers):
            if self.btts_calls:
                raise RuntimeError("provider down")
            return await super().event_odds(event_id, markets=markets, bookmakers=bookmakers)

    with pytest.raises(RuntimeError):
        await sync_btts(fixtures, FailsSecond(), now=NOW)
    assert await fixtures.fetchval("SELECT count(*) FROM odds_snapshots") == btts_rows()


async def test_btts_horizon_can_be_narrowed(fixtures):
    client = FakeOdds()
    await sync_btts(fixtures, client, now=NOW, horizon=timedelta(hours=24))
    soon = {e["id"] for e in odds_events() if kickoff(e) <= NOW + timedelta(hours=24)}
    assert set(client.btts_calls) == soon
