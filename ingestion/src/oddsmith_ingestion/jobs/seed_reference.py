"""seed_reference: teams, squads and entity_aliases for every club in the season.

Cost on API-Football: 1 (teams) + 20 (squads) [+ ~3 pages x 20 teams for full names].
"""

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

import asyncpg

from oddsmith_ingestion import mapping
from oddsmith_ingestion.job_runs import run_job
from oddsmith_ingestion.reference_data import PLAYER_NICKNAMES, team_reference

logger = logging.getLogger(__name__)

JOB_NAME = "seed_reference"
# A squad smaller than this is treated as a truncated response: its club's missing
# players are not detached. Premier League squads list 25+ players.
MIN_SQUAD_SIZE = 15


class ReferenceSource(Protocol):
    async def teams(self, season: int) -> list[dict[str, Any]]: ...
    async def squad(self, team_id: int) -> list[dict[str, Any]]: ...
    async def get_all(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class TeamRow:
    provider_id: int
    name: str
    short_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class PlayerRow:
    provider_id: int
    team_provider_id: int
    name: str
    position: str | None
    aliases: tuple[str, ...]


def build_team(raw: dict[str, Any]) -> TeamRow:
    team = raw["team"]
    ref = team_reference(team["id"], team["name"])
    if ref is None:
        logger.warning("no curated reference for team %s %r", team["id"], team["name"])
    short_name = ref.short_name if ref else team["name"]
    extra = ref.aliases if ref else ()
    aliases = _unique([short_name, *extra, *([team["code"]] if team.get("code") else [])])
    return TeamRow(team["id"], team["name"], short_name, aliases)


def full_name_aliases(players_response: list[dict[str, Any]]) -> dict[int, tuple[str, ...]]:
    """From /players: 'Kai Lukas Havertz' and the common form 'Kai Havertz'."""
    result: dict[int, tuple[str, ...]] = {}
    for item in players_response:
        player = item["player"]
        first, last = (
            (player.get("firstname") or "").strip(),
            (player.get("lastname") or "").strip(),
        )
        if first and last:
            result[player["id"]] = _unique(
                [f"{first} {last}", f"{first.split()[0]} {last.split()[-1]}"]
            )
    return result


def build_players(
    squad_response: list[dict[str, Any]],
    team_provider_id: int,
    full_names: dict[int, tuple[str, ...]],
) -> list[PlayerRow]:
    rows = []
    for entry in squad_response:
        for player in entry["players"]:
            derived = mapping.player_name_aliases(player["name"])
            nicknames = [
                nick
                for alias in derived
                for nick in PLAYER_NICKNAMES.get(
                    (team_provider_id, mapping.alias_search(alias)), ()
                )
            ]
            aliases = _unique(
                [
                    a
                    for a in [*sorted(derived), *full_names.get(player["id"], ()), *nicknames]
                    if a != player["name"]
                ]
            )
            rows.append(
                PlayerRow(
                    player["id"],
                    team_provider_id,
                    player["name"],
                    mapping.position(player.get("position")),
                    aliases,
                )
            )
    return rows


async def seed_reference(
    pool: asyncpg.Pool, client: ReferenceSource, *, season: int, include_full_names: bool = True
) -> int:
    return await run_job(pool, JOB_NAME, lambda: _seed(pool, client, season, include_full_names))


async def _seed(
    pool: asyncpg.Pool, client: ReferenceSource, season: int, include_full_names: bool
) -> int:
    teams = [build_team(raw) for raw in await client.teams(season)]
    players: list[PlayerRow] = []
    for team in teams:
        squad = await client.squad(team.provider_id)
        full_names = {}
        if include_full_names and squad:
            full_names = full_name_aliases(
                await client.get_all("players", {"team": team.provider_id, "season": season})
            )
        players = [*players, *build_players(squad, team.provider_id, full_names)]

    async with pool.acquire() as conn, conn.transaction():
        players = _one_club_each(players, await _current_clubs(conn, players))
        team_ids = await _upsert_teams(conn, teams)
        player_ids = await _upsert_players(conn, players, team_ids)
        await _detach_departed(conn, players)
        await _insert_aliases(conn, teams, team_ids, players, player_ids)
    logger.info("seed_reference: %s teams, %s players", len(teams), len(players))
    return len(teams) + len(players)


async def _current_clubs(conn: asyncpg.Connection, players: list[PlayerRow]) -> dict[int, int]:
    """player provider_id -> current team provider_id, for players already stored."""
    rows = await conn.fetch(
        """SELECT p.provider_id, t.provider_id AS team_provider_id
           FROM players p JOIN teams t ON t.id = p.team_id
           WHERE p.provider_id = ANY($1::int[])""",
        [p.provider_id for p in players],
    )
    return {r["provider_id"]: r["team_provider_id"] for r in rows}


def _one_club_each(players: list[PlayerRow], current: dict[int, int]) -> list[PlayerRow]:
    """A player listed in two squads (loan, mid-window move) keeps his stored club if it is
    one of them, else the first squad listing him."""
    by_player: dict[int, list[PlayerRow]] = {}
    for p in players:
        by_player = {**by_player, p.provider_id: [*by_player.get(p.provider_id, []), p]}
    chosen = []
    for provider_id, listings in by_player.items():
        if len(listings) > 1:
            logger.warning(
                "player %s (%s) is in %s squads: %s",
                provider_id,
                listings[0].name,
                len(listings),
                [x.team_provider_id for x in listings],
            )
        stored = [x for x in listings if x.team_provider_id == current.get(provider_id)]
        chosen.append((stored or listings)[0])
    return chosen


async def _upsert_teams(conn: asyncpg.Connection, teams: list[TeamRow]) -> dict[int, int]:
    await conn.executemany(
        """INSERT INTO teams (provider_id, name, short_name, aliases, fetched_at)
           VALUES ($1, $2, $3, $4, now())
           ON CONFLICT (provider_id) DO UPDATE SET name = EXCLUDED.name,
             short_name = EXCLUDED.short_name, aliases = EXCLUDED.aliases, fetched_at = now()""",
        [(t.provider_id, t.name, t.short_name, list(t.aliases)) for t in teams],
    )
    return await _id_map(conn, "teams", [t.provider_id for t in teams])


async def _upsert_players(
    conn: asyncpg.Connection, players: list[PlayerRow], team_ids: dict[int, int]
) -> dict[int, int]:
    await conn.executemany(
        """INSERT INTO players (provider_id, team_id, name, position, aliases, fetched_at)
           VALUES ($1, $2, $3, $4, $5, now())
           ON CONFLICT (provider_id) DO UPDATE SET team_id = EXCLUDED.team_id,
             name = EXCLUDED.name, position = COALESCE(EXCLUDED.position, players.position),
             aliases = EXCLUDED.aliases, fetched_at = now()""",
        [
            (p.provider_id, team_ids[p.team_provider_id], p.name, p.position, list(p.aliases))
            for p in players
        ],
    )
    return await _id_map(conn, "players", [p.provider_id for p in players])


async def _detach_departed(conn: asyncpg.Connection, players: list[PlayerRow]) -> None:
    """Players no longer in their club's squad get team_id NULL. Clubs whose squad came back
    smaller than MIN_SQUAD_SIZE are left alone, so a truncated response can't empty a club."""
    sizes = Counter(p.team_provider_id for p in players)
    trusted = [team for team, size in sizes.items() if size >= MIN_SQUAD_SIZE]
    skipped = sorted(team for team, size in sizes.items() if size < MIN_SQUAD_SIZE)
    if skipped:
        logger.warning("squads under %s players, not detaching: %s", MIN_SQUAD_SIZE, skipped)
    await conn.execute(
        """UPDATE players p SET team_id = NULL, fetched_at = now() FROM teams t
           WHERE p.team_id = t.id AND t.provider_id = ANY($1::int[])
             AND NOT (p.provider_id = ANY($2::int[]))""",
        trusted,
        [p.provider_id for p in players],
    )


async def _insert_aliases(
    conn: asyncpg.Connection,
    teams: list[TeamRow],
    team_ids: dict[int, int],
    players: list[PlayerRow],
    player_ids: dict[int, int],
) -> None:
    candidates = [
        *(
            (alias, "team", team_ids[t.provider_id])
            for t in teams
            for alias in (t.name, *t.aliases)
        ),
        *(
            (alias, "player", player_ids[p.provider_id])
            for p in players
            for alias in (p.name, *p.aliases)
        ),
    ]
    rows = {
        (mapping.alias_search(alias), kind, entity_id): alias
        for alias, kind, entity_id in reversed(candidates)  # first spelling wins
    }
    for kind, ids in (("team", team_ids.values()), ("player", player_ids.values())):
        keep = [(search, entity_id) for (search, k, entity_id) in rows if k == kind]
        await _prune_aliases(conn, kind, list(ids), keep)
    await conn.executemany(
        """INSERT INTO entity_aliases (alias, alias_search, entity_type, entity_id)
           VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING""",
        [(alias, search, kind, entity_id) for (search, kind, entity_id), alias in rows.items()],
    )


async def _prune_aliases(
    conn: asyncpg.Connection, kind: str, entity_ids: list[int], keep: list[tuple[str, int]]
) -> None:
    """Delete aliases of the seeded entities that this run no longer produces."""
    await conn.execute(
        """DELETE FROM entity_aliases a
           WHERE a.entity_type = $1 AND a.entity_id = ANY($2::bigint[])
             AND NOT EXISTS (
               SELECT 1 FROM unnest($3::text[], $4::bigint[]) AS k(alias_search, entity_id)
               WHERE k.alias_search = a.alias_search AND k.entity_id = a.entity_id)""",
        kind,
        entity_ids,
        [search for search, _ in keep],
        [entity_id for _, entity_id in keep],
    )


async def _id_map(conn: asyncpg.Connection, table: str, provider_ids: list[int]) -> dict[int, int]:
    rows = await conn.fetch(
        f"SELECT provider_id, id FROM {table} WHERE provider_id = ANY($1::int[])",  # noqa: S608
        provider_ids,
    )
    return {r["provider_id"]: r["id"] for r in rows}


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))
