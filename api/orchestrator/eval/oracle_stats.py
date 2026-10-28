"""Oracles for the stats tools: figures recomputed from fixtures and the *_match_stats tables."""

from datetime import date, datetime
from typing import Any

import asyncpg

from orchestrator.eval.oracle_common import Expected, iso, number, rate_pairs

SEASON = "2026/27"
COUNT_STATS = (
    "goals",
    "assists",
    "shots",
    "shots_on_target",
    "yellow_cards",
    "red_cards",
    "fouls",
    "tackles",
    "key_passes",
)
MATCH_STATS = ("minutes", "goals", "assists", "shots", "yellow_cards", "red_cards")

_PLAYER_SQL = """
SELECT pms.fixture_id, pms.minutes, pms.goals, pms.assists, pms.shots, pms.shots_on_target,
       pms.xg, pms.xa, pms.yellow_cards, pms.red_cards, pms.fouls, pms.tackles,
       pms.key_passes, pms.fetched_at
FROM player_match_stats pms
JOIN fixtures f ON f.id = pms.fixture_id
WHERE pms.player_id = $1
  AND f.season = $2
  AND f.status = 'finished'
  AND pms.minutes > 0
  AND ($3::text = 'all' OR ($3 = 'home') = (pms.team_id = f.home_id))
  AND ($4::bigint IS NULL
       OR $4 = CASE WHEN pms.team_id = f.home_id THEN f.away_id ELSE f.home_id END)
ORDER BY f.kickoff_at DESC
LIMIT $5::int
"""

# Results come from the fixture's score, not from team_match_stats.
_TEAM_SQL = """
SELECT f.id,
       CASE WHEN f.home_id = $1 THEN f.home_score ELSE f.away_score END AS goals_for,
       CASE WHEN f.home_id = $1 THEN f.away_score ELSE f.home_score END AS goals_against,
       tms.xg_for, tms.xg_against, tms.corners, tms.yellow_cards, tms.red_cards, tms.fetched_at
FROM fixtures f
LEFT JOIN team_match_stats tms ON tms.fixture_id = f.id AND tms.team_id = $1
WHERE f.season = $2
  AND f.status = 'finished'
  AND $1 IN (f.home_id, f.away_id)
  AND ($3::text = 'all' OR ($3 = 'home') = (f.home_id = $1))
ORDER BY f.kickoff_at DESC
LIMIT $4::int
"""

_MEETINGS_SQL = """
SELECT f.id, f.home_id, f.home_score, f.away_score, f.fetched_at,
       (SELECT sum(t.yellow_cards + t.red_cards) FROM team_match_stats t
        WHERE t.fixture_id = f.id) AS total_cards
FROM fixtures f
WHERE f.status = 'finished'
  AND f.home_score IS NOT NULL AND f.away_score IS NOT NULL
  AND LEAST(f.home_id, f.away_id) = LEAST($1::bigint, $2::bigint)
  AND GREATEST(f.home_id, f.away_id) = GREATEST($1::bigint, $2::bigint)
ORDER BY f.kickoff_at DESC
LIMIT $3::int
"""

_BOOKINGS_SQL = """
SELECT pms.player_id, sum(pms.yellow_cards) AS yellow_cards, sum(pms.red_cards) AS red_cards,
       count(*) FILTER (WHERE pms.minutes > 0) AS appearances, min(pms.fetched_at) AS oldest
FROM player_match_stats pms
WHERE pms.fixture_id = ANY($1::bigint[])
GROUP BY pms.player_id
HAVING sum(pms.yellow_cards + pms.red_cards) > 0
"""

_FIXTURES_BY_ID_SQL = """
SELECT f.id, f.season, f.matchweek, f.kickoff_at, f.status, f.home_id, f.away_id,
       f.home_score, f.away_score, f.fetched_at, h.name AS home_name, a.name AS away_name,
       (f.kickoff_at AT TIME ZONE 'Europe/London')::date AS uk_date
FROM fixtures f
JOIN teams h ON h.id = f.home_id
JOIN teams a ON a.id = f.away_id
WHERE f.id = ANY($1::bigint[])
"""

_FIXTURE_COUNT_SQL = """
SELECT count(*)
FROM fixtures f
WHERE f.season = $1
  AND ($2::bigint IS NULL OR f.home_id = $2 OR f.away_id = $2)
  AND ($3::bigint IS NULL OR f.home_id = $3 OR f.away_id = $3)
  AND ($4::int IS NULL OR f.matchweek = $4)
  AND ($5::date IS NULL OR (f.kickoff_at AT TIME ZONE 'Europe/London')::date >= $5)
  AND ($6::date IS NULL OR (f.kickoff_at AT TIME ZONE 'Europe/London')::date <= $6)
  AND ($7::text = 'all' OR f.status = $7)
"""

_TABLE_SQL = """
SELECT m.team_id, t.name,
       count(*)                                   AS played,
       count(*) FILTER (WHERE m.gf > m.ga)        AS won,
       count(*) FILTER (WHERE m.gf = m.ga)        AS drawn,
       count(*) FILTER (WHERE m.gf < m.ga)        AS lost,
       sum(m.gf)                                  AS goals_for,
       sum(m.ga)                                  AS goals_against
FROM (
    SELECT home_id AS team_id, home_score AS gf, away_score AS ga
    FROM fixtures WHERE season = $1 AND status = 'finished' AND $2::text IN ('all', 'home')
    UNION ALL
    SELECT away_id, away_score, home_score
    FROM fixtures WHERE season = $1 AND status = 'finished' AND $2::text IN ('all', 'away')
) m
JOIN teams t ON t.id = m.team_id
GROUP BY m.team_id, t.name
"""

_TABLE_OLDEST_SQL = """
SELECT min(tms.fetched_at)
FROM team_match_stats tms
JOIN fixtures f ON f.id = tms.fixture_id
WHERE f.season = $1 AND f.status = 'finished' AND ($2::text = 'all' OR tms.venue = $2)
"""

_AVAILABILITY_SQL = """
SELECT av.player_id, av.status, av.reason, av.expected_return, av.fetched_at
FROM availability av
WHERE ($1::bigint IS NULL
       OR av.team_id IN (SELECT home_id FROM fixtures WHERE id = $1
                         UNION SELECT away_id FROM fixtures WHERE id = $1))
  AND ($2::bigint IS NULL OR av.team_id = $2)
  AND ($3::bigint IS NULL OR av.player_id = $3)
"""

_LAST_AVAILABILITY_SYNC_SQL = """
SELECT max(finished_at) FROM job_runs WHERE name = 'sync_availability' AND status = 'success'
"""


def _total(rows: list[asyncpg.Record], key: str) -> float | None:
    known = [float(r[key]) for r in rows if r[key] is not None]
    return sum(known) if known else None


async def player_stats(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    rows = await conn.fetch(
        _PLAYER_SQL,
        args["player_id"],
        args["season"],
        args["venue"],
        args.get("opponent_team_id"),
        args.get("last_n"),
    )
    minutes = sum(r["minutes"] for r in rows)
    by_fixture = {r["fixture_id"]: r for r in rows}
    pairs: list[tuple] = [
        ("appearances", data["appearances"], len(rows)),
        ("minutes", data["minutes"], minutes),
        ("matches listed", sorted(m["fixture_id"] for m in data["matches"]), sorted(by_fixture)),
    ]
    for key in COUNT_STATS:
        total = sum(r[key] for r in rows)
        pairs += [
            (f"totals.{key}", data["totals"][key], total),
            (f"per90.{key}", data["per90"][key], total * 90 / minutes),
        ]
    for key in ("xg", "xa"):
        pairs += [(f"totals.{key}", data["totals"][key], _total(rows, key))]
    for match in data["matches"]:
        row = by_fixture.get(match["fixture_id"])
        pairs += [
            (f"match {match['fixture_id']} {key}", match[key], row[key])
            for key in MATCH_STATS
            if row is not None
        ]
    return Expected(pairs, min(r["fetched_at"] for r in rows))


def _result(row: asyncpg.Record) -> str:
    if row["goals_for"] > row["goals_against"]:
        return "W"
    return "D" if row["goals_for"] == row["goals_against"] else "L"


def _average(rows: list[asyncpg.Record], key: str) -> float | None:
    known = [float(r[key]) for r in rows if r[key] is not None]
    return sum(known) / len(known) if known else None


async def team_stats(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    newest_first = await conn.fetch(
        _TEAM_SQL, args["team_id"], args["season"], args["venue"], args.get("last_n")
    )
    rows = list(reversed(newest_first))
    results = [_result(r) for r in rows]
    played = len(rows)
    cards = sum((r["yellow_cards"] or 0) + (r["red_cards"] or 0) for r in rows) / played
    pairs: list[tuple] = [
        ("played", data["played"], played),
        ("won", data["won"], results.count("W")),
        ("drawn", data["drawn"], results.count("D")),
        ("lost", data["lost"], results.count("L")),
        ("form", data["form"], "".join(results)),
        ("goals_for", data["goals_for"], sum(r["goals_for"] for r in rows)),
        ("goals_against", data["goals_against"], sum(r["goals_against"] for r in rows)),
        ("xg_for", data["xg_for"], _total(rows, "xg_for")),
        ("xg_against", data["xg_against"], _total(rows, "xg_against")),
        ("corners_per_match", data["corners_per_match"], _average(rows, "corners")),
        ("cards_per_match", data["cards_per_match"], cards),
        ("matches listed", [m["fixture_id"] for m in data["matches"]], [r["id"] for r in rows]),
        *rate_pairs(
            "over_2_5",
            data["over_2_5"],
            sum(1 for r in rows if r["goals_for"] + r["goals_against"] >= 3),
            played,
        ),
        *rate_pairs(
            "btts",
            data["btts"],
            sum(1 for r in rows if r["goals_for"] > 0 and r["goals_against"] > 0),
            played,
        ),
        *rate_pairs(
            "clean_sheets",
            data["clean_sheets"],
            sum(1 for r in rows if r["goals_against"] == 0),
            played,
        ),
    ]
    fetched = [r["fetched_at"] for r in rows if r["fetched_at"] is not None]
    return Expected(pairs, min(fetched) if fetched else now)


async def head_to_head(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    team_a = args["team_a_id"]
    rows = await conn.fetch(_MEETINGS_SQL, team_a, args["team_b_id"], args["limit"])
    margins = [
        (r["home_score"] - r["away_score"]) * (1 if r["home_id"] == team_a else -1) for r in rows
    ]
    goals = [r["home_score"] + r["away_score"] for r in rows]
    played = len(rows)
    summary = data["summary"]
    by_id = {r["id"]: r for r in rows}
    pairs: list[tuple] = [
        ("meetings listed", [m["fixture_id"] for m in data["meetings"]], [r["id"] for r in rows]),
        ("summary.played", summary["played"], played),
        ("summary.team_a_wins", summary["team_a_wins"], sum(1 for m in margins if m > 0)),
        ("summary.draws", summary["draws"], sum(1 for m in margins if m == 0)),
        ("summary.team_b_wins", summary["team_b_wins"], sum(1 for m in margins if m < 0)),
        ("summary.avg_goals", summary["avg_goals"], sum(goals) / played),
        *rate_pairs("summary.over_2_5", summary["over_2_5"], sum(g >= 3 for g in goals), played),
        *rate_pairs(
            "summary.btts",
            summary["btts"],
            sum(1 for r in rows if r["home_score"] > 0 and r["away_score"] > 0),
            played,
        ),
    ]
    for meeting in data["meetings"]:
        row = by_id.get(meeting["fixture_id"])
        if row is not None:
            label = f"meeting {meeting['fixture_id']}"
            pairs += [
                (f"{label} home_score", meeting["home_score"], row["home_score"]),
                (f"{label} away_score", meeting["away_score"], row["away_score"]),
                (f"{label} total_cards", meeting["total_cards"], number(row["total_cards"])),
            ]
    oldest = [r["fetched_at"] for r in rows]
    if "most_booked" in data:
        booked = await conn.fetch(_BOOKINGS_SQL, [r["id"] for r in rows])
        by_player = {b["player_id"]: b for b in booked}
        top = max((b["yellow_cards"] + b["red_cards"] for b in booked), default=0)
        listed = data["most_booked"]
        listed_top = max((b["yellow_cards"] + b["red_cards"] for b in listed), default=0)
        pairs += [("most cards by one player", listed_top, top)]
        for entry in listed:
            player_id = entry["player"]["id"]
            sql = by_player.get(player_id)
            for key in ("yellow_cards", "red_cards", "appearances"):
                pairs += [(f"booked {player_id} {key}", entry[key], sql and number(sql[key]))]
        oldest += [
            by_player[e["player"]["id"]]["oldest"] for e in listed if e["player"]["id"] in by_player
        ]
    return Expected(pairs, min(oldest))


def _fixture_pairs(fixture: dict[str, Any], row: asyncpg.Record | None) -> list[tuple]:
    label = f"fixture {fixture['fixture_id']}"
    if row is None:
        return [(label, "listed", "no such fixture")]
    return [
        (f"{label} kickoff_at", fixture["kickoff_at"], iso(row["kickoff_at"])),
        (f"{label} status", fixture["status"], row["status"]),
        (f"{label} matchweek", fixture["matchweek"], row["matchweek"]),
        (f"{label} home", fixture["home"]["name"], row["home_name"]),
        (f"{label} away", fixture["away"]["name"], row["away_name"]),
        (f"{label} home_score", fixture["home_score"], row["home_score"]),
        (f"{label} away_score", fixture["away_score"], row["away_score"]),
    ]


def _passes_filters(row: asyncpg.Record, args: dict[str, Any]) -> bool:
    teams = (row["home_id"], row["away_id"])
    date_from, date_to = args.get("date_from"), args.get("date_to")
    return (
        row["season"] == SEASON
        and args.get("team_id") in (None, *teams)
        and args.get("opponent_team_id") in (None, *teams)
        and args.get("matchweek") in (None, row["matchweek"])
        and (date_from is None or row["uk_date"] >= date.fromisoformat(date_from))
        and (date_to is None or row["uk_date"] <= date.fromisoformat(date_to))
        and args["status"] in ("all", row["status"])
    )


async def fixtures(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    listed = data["fixtures"]
    rows = await conn.fetch(_FIXTURES_BY_ID_SQL, [f["fixture_id"] for f in listed])
    by_id = {r["id"]: r for r in rows}
    matching = await conn.fetchval(
        _FIXTURE_COUNT_SQL,
        SEASON,
        args.get("team_id"),
        args.get("opponent_team_id"),
        args.get("matchweek"),
        args.get("date_from") and date.fromisoformat(args["date_from"]),
        args.get("date_to") and date.fromisoformat(args["date_to"]),
        args["status"],
    )
    pairs: list[tuple] = [("fixtures listed", len(listed), min(matching, args["limit"]))]
    for fixture in listed:
        row = by_id.get(fixture["fixture_id"])
        pairs += _fixture_pairs(fixture, row)
        if row is not None:
            pairs += [
                (f"fixture {row['id']} matches the filters", _passes_filters(row, args), True)
            ]
    return Expected(pairs, min((r["fetched_at"] for r in rows), default=now))


def _standing(row: asyncpg.Record) -> tuple:
    points = row["won"] * 3 + row["drawn"]
    difference = row["goals_for"] - row["goals_against"]
    return (-points, -difference, -row["goals_for"], row["name"])


async def league_table(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    records = sorted(await conn.fetch(_TABLE_SQL, SEASON, args["venue"]), key=_standing)
    listed = {r["team"]["id"]: r for r in data["rows"]}
    pairs: list[tuple] = [("teams in table", len(data["rows"]), len(records))]
    for position, record in enumerate(records, start=1):
        row = listed.get(record["team_id"])
        label = record["name"]
        if row is None:
            pairs += [(label, "missing", "in table")]
            continue
        goals_for, goals_against = int(record["goals_for"]), int(record["goals_against"])
        pairs += [
            (f"{label} position", row["position"], position),
            (f"{label} played", row["played"], record["played"]),
            (f"{label} won", row["won"], record["won"]),
            (f"{label} drawn", row["drawn"], record["drawn"]),
            (f"{label} lost", row["lost"], record["lost"]),
            (f"{label} goals_for", row["goals_for"], goals_for),
            (f"{label} goals_against", row["goals_against"], goals_against),
            (f"{label} goal_difference", row["goal_difference"], goals_for - goals_against),
            (f"{label} points", row["points"], record["won"] * 3 + record["drawn"]),
        ]
    oldest = await conn.fetchval(_TABLE_OLDEST_SQL, SEASON, args["venue"])
    return Expected(pairs, oldest or now)


def _absence(player_id: int, status: str, reason: str | None, returns: str | None) -> tuple:
    return (player_id, status, reason, returns)


async def availability(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    rows = await conn.fetch(
        _AVAILABILITY_SQL, args.get("fixture_id"), args.get("team_id"), args.get("player_id")
    )
    expected = sorted(
        _absence(
            r["player_id"],
            r["status"],
            r["reason"],
            r["expected_return"] and r["expected_return"].isoformat(),
        )
        for r in rows
    )
    listed = sorted(
        _absence(e["player"]["id"], e["status"], e["reason"], e["expected_return"])
        for e in data["entries"]
    )
    last_sync = await conn.fetchval(_LAST_AVAILABILITY_SYNC_SQL)
    fetched = [r["fetched_at"] for r in rows] + ([last_sync] if last_sync else [])
    return Expected([("absences", listed, expected)], min(fetched, default=now))
