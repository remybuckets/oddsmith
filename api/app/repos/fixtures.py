"""fixtures + teams: the next matchweek for the home strip."""

from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True)
class TeamRef:
    id: int
    name: str
    short_name: str


@dataclass(frozen=True)
class FixtureRow:
    fixture_id: int
    matchweek: int | None
    kickoff_at: datetime
    status: str
    home: TeamRef
    away: TeamRef
    home_score: int | None
    away_score: int | None


async def next_matchweek(pool: asyncpg.Pool, now: datetime) -> list[FixtureRow]:
    """Every fixture in the matchweek of the next scheduled kick-off; empty if none."""
    rows = await pool.fetch(
        """
        WITH next_mw AS (
            SELECT season, matchweek FROM fixtures
            WHERE kickoff_at >= $1 AND status = 'scheduled' AND matchweek IS NOT NULL
            ORDER BY kickoff_at
            LIMIT 1
        )
        SELECT f.id, f.matchweek, f.kickoff_at, f.status, f.home_score, f.away_score,
               h.id AS home_id, h.name AS home_name, h.short_name AS home_short,
               a.id AS away_id, a.name AS away_name, a.short_name AS away_short
        FROM fixtures f
        JOIN next_mw USING (season, matchweek)
        JOIN teams h ON h.id = f.home_id
        JOIN teams a ON a.id = f.away_id
        ORDER BY f.kickoff_at, f.id
        """,
        now,
    )
    return [
        FixtureRow(
            fixture_id=row["id"],
            matchweek=row["matchweek"],
            kickoff_at=row["kickoff_at"],
            status=row["status"],
            home=TeamRef(row["home_id"], row["home_name"], row["home_short"]),
            away=TeamRef(row["away_id"], row["away_name"], row["away_short"]),
            home_score=row["home_score"],
            away_score=row["away_score"],
        )
        for row in rows
    ]
