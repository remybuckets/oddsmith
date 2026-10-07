"""sync_results: scores, team match stats and player match stats for kicked-off fixtures.

A fixture is fetched from kick-off + 2h until it is finished and has both team and player
stats. Uses /fixtures?ids= (Pro plan): 1 request per 20 fixtures.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import asyncpg

from oddsmith_ingestion import mapping
from oddsmith_ingestion.job_runs import run_job
from oddsmith_ingestion.providers.api_football import MAX_IDS_PER_REQUEST
from oddsmith_ingestion.repository import ensure_players, id_map

JOB_NAME = "sync_results"
RESULT_DELAY = timedelta(hours=2)
# How far back a scheduled run looks for missing stats; a Fri-Mon matchweek spans 3 days+.
DEFAULT_WINDOW = timedelta(days=4)


class ResultSource(Protocol):
    async def fixtures_by_ids(self, ids: list[int]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class TeamStatRow:
    team_provider_id: int
    venue: str
    goals_for: int
    goals_against: int
    xg_for: Decimal | None
    xg_against: Decimal | None
    corners: int | None
    yellow_cards: int
    red_cards: int


@dataclass(frozen=True)
class PlayerStatRow:
    player_provider_id: int
    name: str
    position: str | None
    team_provider_id: int
    minutes: int
    goals: int
    assists: int
    shots: int
    shots_on_target: int
    yellow_cards: int
    red_cards: int
    fouls: int
    tackles: int
    key_passes: int


def team_stat_rows(detail: dict[str, Any]) -> list[TeamStatRow]:
    """Both teams' rows, or [] if the provider hasn't published stats for both yet."""
    goals = detail["goals"]
    by_team = {
        s["team"]["id"]: {x["type"]: x["value"] for x in s["statistics"]}
        for s in detail.get("statistics") or []
    }
    home, away = detail["teams"]["home"]["id"], detail["teams"]["away"]["id"]
    if set(by_team) != {home, away} or goals["home"] is None or goals["away"] is None:
        return []
    sides = (
        ("home", home, away, goals["home"], goals["away"]),
        ("away", away, home, goals["away"], goals["home"]),
    )
    return [
        TeamStatRow(
            team_provider_id=team,
            venue=venue,
            goals_for=gf,
            goals_against=ga,
            xg_for=_decimal(by_team[team].get("expected_goals")),
            xg_against=_decimal(by_team[opponent].get("expected_goals")),
            corners=by_team[team].get("Corner Kicks"),
            yellow_cards=by_team[team].get("Yellow Cards") or 0,
            red_cards=by_team[team].get("Red Cards") or 0,
        )
        for venue, team, opponent, gf, ga in sides
    ]


def player_stat_rows(detail: dict[str, Any]) -> list[PlayerStatRow]:
    """One row per player who played (unused substitutes have no minutes)."""
    rows = []
    for team in detail.get("players") or []:
        for entry in team["players"]:
            s = entry["statistics"][0]
            if not s["games"]["minutes"]:
                continue
            rows.append(
                PlayerStatRow(
                    player_provider_id=entry["player"]["id"],
                    name=entry["player"]["name"],
                    position=s["games"].get("position"),
                    team_provider_id=team["team"]["id"],
                    minutes=s["games"]["minutes"],
                    goals=s["goals"]["total"] or 0,
                    assists=s["goals"]["assists"] or 0,
                    shots=s["shots"]["total"] or 0,
                    shots_on_target=s["shots"]["on"] or 0,
                    yellow_cards=s["cards"]["yellow"] or 0,
                    red_cards=s["cards"]["red"] or 0,
                    fouls=s["fouls"]["committed"] or 0,
                    tackles=s["tackles"]["total"] or 0,
                    key_passes=s["passes"]["key"] or 0,
                )
            )
    return rows


async def pending_fixture_ids(
    conn: asyncpg.Connection, season: int, now: datetime, window: timedelta | None
) -> list[int]:
    rows = await conn.fetch(
        """SELECT f.provider_id FROM fixtures f
           WHERE f.season = $1 AND f.kickoff_at <= $2
             AND ($3::timestamptz IS NULL OR f.kickoff_at >= $3)
             AND f.status NOT IN ('postponed', 'cancelled')
             AND (f.status <> 'finished'
                  OR NOT EXISTS (SELECT 1 FROM team_match_stats t WHERE t.fixture_id = f.id)
                  OR NOT EXISTS (SELECT 1 FROM player_match_stats p WHERE p.fixture_id = f.id))
           ORDER BY f.kickoff_at, f.provider_id""",
        mapping.season_label(season),
        now - RESULT_DELAY,
        now - window if window is not None else None,
    )
    return [r["provider_id"] for r in rows]


async def write_result(conn: asyncpg.Connection, detail: dict[str, Any]) -> int:
    """Update one fixture's status and score; if finished, write its stats. Returns rows."""
    fixture = detail["fixture"]
    status = mapping.fixture_status(fixture["status"]["short"])
    fixture_id = await conn.fetchval(
        """UPDATE fixtures SET status = $2, home_score = $3, away_score = $4,
             kickoff_at = $5, fetched_at = now() WHERE provider_id = $1 RETURNING id""",
        fixture["id"],
        status,
        detail["goals"]["home"],
        detail["goals"]["away"],
        datetime.fromisoformat(fixture["date"]),
    )
    if fixture_id is None:
        raise ValueError(f"fixture {fixture['id']} not in fixtures; run sync_fixtures first")
    teams, players = team_stat_rows(detail), player_stat_rows(detail)
    if status != "finished" or not teams or not players:
        return 0
    await _upsert_team_stats(conn, fixture_id, teams)
    await _upsert_player_stats(conn, fixture_id, players)
    return len(teams) + len(players)


async def fetch_results(
    pool: asyncpg.Pool,
    client: ResultSource,
    season: int,
    now: datetime,
    window: timedelta | None,
) -> int:
    """Shared with backfill_season."""
    async with pool.acquire() as conn:
        pending = await pending_fixture_ids(conn, season, now, window)
    written = 0
    for start in range(0, len(pending), MAX_IDS_PER_REQUEST):
        details = await client.fixtures_by_ids(pending[start : start + MAX_IDS_PER_REQUEST])
        async with pool.acquire() as conn, conn.transaction():  # one batch commits as a unit
            for detail in details:
                written += await write_result(conn, detail)
    return written


async def sync_results(
    pool: asyncpg.Pool,
    client: ResultSource,
    *,
    season: int,
    now: datetime | None = None,
    window: timedelta | None = DEFAULT_WINDOW,
) -> int:
    at = now or datetime.now(UTC)
    return await run_job(pool, JOB_NAME, lambda: fetch_results(pool, client, season, at, window))


async def _upsert_team_stats(
    conn: asyncpg.Connection, fixture_id: int, rows: list[TeamStatRow]
) -> None:
    team_ids = await id_map(conn, "teams", [r.team_provider_id for r in rows])
    await conn.executemany(
        """INSERT INTO team_match_stats (fixture_id, team_id, venue, goals_for, goals_against,
             xg_for, xg_against, corners, yellow_cards, red_cards, fetched_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
           ON CONFLICT (fixture_id, team_id) DO UPDATE SET venue = EXCLUDED.venue,
             goals_for = EXCLUDED.goals_for, goals_against = EXCLUDED.goals_against,
             xg_for = EXCLUDED.xg_for, xg_against = EXCLUDED.xg_against,
             corners = EXCLUDED.corners, yellow_cards = EXCLUDED.yellow_cards,
             red_cards = EXCLUDED.red_cards, fetched_at = now()""",
        [
            (
                fixture_id,
                team_ids[r.team_provider_id],
                r.venue,
                r.goals_for,
                r.goals_against,
                r.xg_for,
                r.xg_against,
                r.corners,
                r.yellow_cards,
                r.red_cards,
            )
            for r in rows
        ],
    )


async def _upsert_player_stats(
    conn: asyncpg.Connection, fixture_id: int, rows: list[PlayerStatRow]
) -> None:
    player_ids = await ensure_players(
        conn, [(r.player_provider_id, r.name, r.position) for r in rows]
    )
    team_ids = await id_map(conn, "teams", [r.team_provider_id for r in rows])
    await conn.executemany(
        """INSERT INTO player_match_stats (fixture_id, player_id, team_id, minutes, goals,
             assists, shots, shots_on_target, yellow_cards, red_cards, fouls, tackles,
             key_passes, fetched_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, now())
           ON CONFLICT (fixture_id, player_id) DO UPDATE SET team_id = EXCLUDED.team_id,
             minutes = EXCLUDED.minutes, goals = EXCLUDED.goals, assists = EXCLUDED.assists,
             shots = EXCLUDED.shots, shots_on_target = EXCLUDED.shots_on_target,
             yellow_cards = EXCLUDED.yellow_cards, red_cards = EXCLUDED.red_cards,
             fouls = EXCLUDED.fouls, tackles = EXCLUDED.tackles,
             key_passes = EXCLUDED.key_passes, fetched_at = now()""",
        [
            (
                fixture_id,
                player_ids[r.player_provider_id],
                team_ids[r.team_provider_id],
                r.minutes,
                r.goals,
                r.assists,
                r.shots,
                r.shots_on_target,
                r.yellow_cards,
                r.red_cards,
                r.fouls,
                r.tackles,
                r.key_passes,
            )
            for r in rows
        ],
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
