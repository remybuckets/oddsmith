"""sync_fixtures: the season's schedule, kick-off changes, statuses and scores.

Cost on API-Football: 1 request per run.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import asyncpg

from oddsmith_ingestion import mapping
from oddsmith_ingestion.job_runs import run_job
from oddsmith_ingestion.repository import ensure_teams

JOB_NAME = "sync_fixtures"


class FixtureSource(Protocol):
    async def fixtures(self, season: int) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class FixtureRow:
    provider_id: int
    season: str
    matchweek: int | None
    home_provider_id: int
    away_provider_id: int
    kickoff_at: datetime
    status: str
    home_score: int | None
    away_score: int | None


def build_fixture(raw: dict[str, Any], season: int) -> FixtureRow:
    return FixtureRow(
        provider_id=raw["fixture"]["id"],
        season=mapping.season_label(season),
        matchweek=mapping.matchweek(raw["league"].get("round")),
        home_provider_id=raw["teams"]["home"]["id"],
        away_provider_id=raw["teams"]["away"]["id"],
        kickoff_at=datetime.fromisoformat(raw["fixture"]["date"]),
        status=mapping.fixture_status(raw["fixture"]["status"]["short"]),
        home_score=raw["goals"]["home"],
        away_score=raw["goals"]["away"],
    )


async def upsert_fixtures(conn: asyncpg.Connection, raw: list[dict[str, Any]], season: int) -> int:
    """Upsert fixtures (creating any unseen teams). Shared with backfill_season."""
    rows = [build_fixture(item, season) for item in raw]  # validate all before writing
    team_ids = await ensure_teams(
        conn, [item["teams"][side] for item in raw for side in ("home", "away")]
    )
    await conn.executemany(
        """INSERT INTO fixtures (provider_id, season, matchweek, home_id, away_id, kickoff_at,
                                 status, home_score, away_score, fetched_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
           ON CONFLICT (provider_id) DO UPDATE SET season = EXCLUDED.season,
             matchweek = EXCLUDED.matchweek, home_id = EXCLUDED.home_id,
             away_id = EXCLUDED.away_id, kickoff_at = EXCLUDED.kickoff_at,
             status = EXCLUDED.status, home_score = EXCLUDED.home_score,
             away_score = EXCLUDED.away_score, fetched_at = now()""",
        [
            (
                r.provider_id,
                r.season,
                r.matchweek,
                team_ids[r.home_provider_id],
                team_ids[r.away_provider_id],
                r.kickoff_at,
                r.status,
                r.home_score,
                r.away_score,
            )
            for r in rows
        ],
    )
    return len(rows)


async def sync_fixtures(pool: asyncpg.Pool, client: FixtureSource, *, season: int) -> int:
    async def work() -> int:
        raw = await client.fixtures(season)
        async with pool.acquire() as conn, conn.transaction():
            return await upsert_fixtures(conn, raw, season)

    return await run_job(pool, JOB_NAME, work)
