"""sync_availability: current injuries and suspensions from API-Football.

Fetches injuries for each club's next scheduled fixture (about 10 requests) and replaces
those clubs' rows, so players who are fit again disappear. No expected return date is
provided by API-Football.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import asyncpg

from oddsmith_ingestion import mapping
from oddsmith_ingestion.job_runs import run_job
from oddsmith_ingestion.repository import ensure_players, id_map

JOB_NAME = "sync_availability"
SOURCE = "api-football"
_SEVERITY = {"injured": 2, "suspended": 2, "doubtful": 1}  # 'Missing' beats 'Questionable'


class InjurySource(Protocol):
    async def injuries(self, season: int, **filters: Any) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class AvailabilityRow:
    player_provider_id: int
    name: str
    team_provider_id: int
    status: str
    reason: str | None


def build_availability(response: list[dict[str, Any]]) -> list[AvailabilityRow]:
    """One row per player (the provider repeats players); skips non-absences."""
    by_player: dict[int, AvailabilityRow] = {}
    for item in response:
        player = item["player"]
        status = mapping.availability_status(player["type"], player.get("reason"))
        if status is None:
            continue
        row = AvailabilityRow(
            player["id"], player["name"], item["team"]["id"], status, player.get("reason")
        )
        kept = by_player.get(row.player_provider_id)
        if kept is None or _SEVERITY[row.status] > _SEVERITY[kept.status]:
            by_player = {**by_player, row.player_provider_id: row}
    return list(by_player.values())


async def next_fixtures(
    conn: asyncpg.Connection, season: int, now: datetime
) -> list[tuple[int, list[int]]]:
    """Each club's next scheduled fixture, as (fixture provider_id, [team ids it covers])."""
    rows = await conn.fetch(
        """SELECT DISTINCT ON (x.team_id) x.team_id, x.provider_id
           FROM (SELECT home_id AS team_id, provider_id, kickoff_at FROM fixtures
                 WHERE season = $1 AND status = 'scheduled' AND kickoff_at > $2
                 UNION ALL
                 SELECT away_id, provider_id, kickoff_at FROM fixtures
                 WHERE season = $1 AND status = 'scheduled' AND kickoff_at > $2) x
           ORDER BY x.team_id, x.kickoff_at""",
        mapping.season_label(season),
        now,
    )
    covered: dict[int, list[int]] = {}
    for r in rows:
        covered = {**covered, r["provider_id"]: [*covered.get(r["provider_id"], []), r["team_id"]]}
    return sorted(covered.items())


async def replace_team_availability(
    conn: asyncpg.Connection, team_ids: list[int], rows: list[AvailabilityRow], now: datetime
) -> int:
    """Upsert `rows` and delete this source's other rows for `team_ids`."""
    player_ids = await ensure_players(conn, [(r.player_provider_id, r.name, None) for r in rows])
    teams = await id_map(conn, "teams", [r.team_provider_id for r in rows])
    await conn.executemany(
        """INSERT INTO availability (team_id, player_id, status, reason, source, updated_at,
                                     fetched_at)
           VALUES ($1, $2, $3, $4, $5, $6, now())
           ON CONFLICT (player_id, source) DO UPDATE SET team_id = EXCLUDED.team_id,
             status = EXCLUDED.status, reason = EXCLUDED.reason, fetched_at = now(),
             updated_at = CASE
               WHEN (availability.status, availability.reason, availability.team_id)
                    IS DISTINCT FROM (EXCLUDED.status, EXCLUDED.reason, EXCLUDED.team_id)
               THEN EXCLUDED.updated_at ELSE availability.updated_at END""",
        [
            (
                teams[r.team_provider_id],
                player_ids[r.player_provider_id],
                r.status,
                r.reason,
                SOURCE,
                now,
            )
            for r in rows
        ],
    )
    await conn.execute(
        """DELETE FROM availability WHERE source = $1 AND team_id = ANY($2::bigint[])
             AND NOT (player_id = ANY($3::bigint[]))""",
        SOURCE,
        team_ids,
        [player_ids[r.player_provider_id] for r in rows],
    )
    return len(rows)


async def sync_availability(
    pool: asyncpg.Pool, client: InjurySource, *, season: int, now: datetime | None = None
) -> int:
    at = now or datetime.now(UTC)

    async def work() -> int:
        async with pool.acquire() as conn:
            fixtures = await next_fixtures(conn, season, at)
        written = 0
        for fixture_id, team_ids in fixtures:
            rows = build_availability(await client.injuries(season, fixture=fixture_id))
            async with pool.acquire() as conn, conn.transaction():
                covered = await _provider_ids(conn, team_ids)
                # A club whose next match is a different fixture is updated from that one.
                own = [r for r in rows if r.team_provider_id in covered]
                written += await replace_team_availability(conn, team_ids, own, datetime.now(UTC))
        return written

    return await run_job(pool, JOB_NAME, work)


async def _provider_ids(conn: asyncpg.Connection, team_ids: list[int]) -> set[int]:
    rows = await conn.fetch("SELECT provider_id FROM teams WHERE id = ANY($1::bigint[])", team_ids)
    return {r["provider_id"] for r in rows}
