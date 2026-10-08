"""Hand-written seed rows for orchestrator tests, shaped like the real schema.

Six clubs, 2026/27 matchweeks 1-3 (finished) and 7 (scheduled), plus two 2025/26 meetings
between Aston Villa and Spurs for head-to-head. Replace with ingestion's recorded shape once
`ingestion/tests/fixtures/` exists.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import asyncpg

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
STATS_FETCHED = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
STALE_FETCHED = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)
SCHEDULE_FETCHED = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)
AVAILABILITY_FETCHED = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)
AVAILABILITY_JOB_FINISHED = datetime(2026, 10, 7, 6, 5, tzinfo=UTC)

ARS, TOT, AVL, BRE, MCI, NEW = 1, 2, 3, 4, 5, 6
SAKA, GABRIEL, MARTINELLI, JESUS, ODEGAARD = 11, 12, 13, 14, 15
ROMERO, SOLANKE, WATKINS, MCGINN, THIAGO, HAALAND, BRUNO = 21, 22, 31, 32, 41, 51, 61

# Fixture 109 has no xG and stale stats rows.
NO_XG_FIXTURES = {109}
STALE_FIXTURES = {109}

TEAMS = [
    (ARS, 42, "Arsenal", "ARS", ["arsenal", "gunners"]),
    (TOT, 47, "Tottenham Hotspur", "TOT", ["tottenham hotspur", "tottenham", "spurs"]),
    (AVL, 66, "Aston Villa", "AVL", ["aston villa", "villa"]),
    (BRE, 55, "Brentford", "BRE", ["brentford", "bees"]),
    (MCI, 50, "Manchester City", "MCI", ["manchester city", "man city", "city"]),
    (NEW, 34, "Newcastle United", "NEW", ["newcastle united", "newcastle", "toon"]),
]

PLAYERS = [
    (SAKA, 1460, ARS, "Bukayo Saka", "FWD", ["bukayo saka", "saka"]),
    (GABRIEL, 22224, ARS, "Gabriel Magalhães", "DEF", ["gabriel", "gabriel magalhaes"]),
    (MARTINELLI, 127769, ARS, "Gabriel Martinelli", "FWD", ["gabriel martinelli", "martinelli"]),
    (JESUS, 643, ARS, "Gabriel Jesus", "FWD", ["gabriel jesus", "jesus"]),
    (ODEGAARD, 37127, ARS, "Martin Ødegaard", "MID", ["martin odegaard", "odegaard"]),
    (ROMERO, 30776, TOT, "Cristian Romero", "DEF", ["cristian romero", "romero", "cuti romero"]),
    (SOLANKE, 18788, TOT, "Dominic Solanke", "FWD", ["dominic solanke", "solanke"]),
    (WATKINS, 19366, AVL, "Ollie Watkins", "FWD", ["ollie watkins", "watkins"]),
    (MCGINN, 19191, AVL, "John McGinn", "MID", ["john mcginn", "mcginn"]),
    (THIAGO, 129718, BRE, "Igor Thiago", "FWD", ["igor thiago", "thiago"]),
    (HAALAND, 1100, MCI, "Erling Haaland", "FWD", ["erling haaland", "haaland"]),
    (BRUNO, 10135, NEW, "Bruno Guimarães", "MID", ["bruno guimaraes", "bruno"]),
]

# Display spelling for aliases whose search form drops accents.
ALIAS_DISPLAY = {"odegaard": "Ødegaard", "gabriel magalhaes": "Gabriel Magalhães"}


def _ko(y: int, m: int, d: int, hh: int = 14, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


# (id, provider_id, season, matchweek, home, away, kickoff, status, home_score, away_score)
FIXTURES = [
    (101, 9101, "2026/27", 1, ARS, BRE, _ko(2026, 8, 22), "finished", 2, 1),
    (102, 9102, "2026/27", 1, AVL, TOT, _ko(2026, 8, 22), "finished", 1, 1),
    (103, 9103, "2026/27", 1, MCI, NEW, _ko(2026, 8, 22), "finished", 3, 0),
    (104, 9104, "2026/27", 2, TOT, ARS, _ko(2026, 8, 29), "finished", 0, 2),
    (105, 9105, "2026/27", 2, BRE, MCI, _ko(2026, 8, 29), "finished", 2, 2),
    (106, 9106, "2026/27", 2, NEW, AVL, _ko(2026, 8, 29), "finished", 1, 0),
    (107, 9107, "2026/27", 3, ARS, AVL, _ko(2026, 9, 12), "finished", 1, 1),
    (108, 9108, "2026/27", 3, TOT, BRE, _ko(2026, 9, 12), "finished", 3, 1),
    (109, 9109, "2026/27", 3, NEW, MCI, _ko(2026, 9, 12), "finished", 1, 2),
    (201, 9201, "2026/27", 7, AVL, TOT, _ko(2026, 10, 17), "scheduled", None, None),
    (202, 9202, "2026/27", 7, BRE, NEW, _ko(2026, 10, 17), "scheduled", None, None),
    (203, 9203, "2026/27", 7, MCI, ARS, _ko(2026, 10, 18, 15, 30), "scheduled", None, None),
    (301, 8301, "2025/26", 24, TOT, AVL, _ko(2026, 2, 1, 16, 30), "finished", 2, 2),
    (302, 8302, "2025/26", 5, AVL, TOT, _ko(2025, 9, 20), "finished", 2, 0),
]

# (fixture, player, team, minutes, goals, assists, shots, sot, xg, xa,
#  yellow, red, fouls, tackles, key_passes)
PLAYER_ROWS = [
    (101, SAKA, ARS, 90, 1, 1, 4, 2, "0.65", "0.40", 0, 0, 1, 2, 3),
    (104, SAKA, ARS, 85, 1, 0, 3, 2, "0.55", "0.10", 1, 0, 2, 1, 2),
    (107, SAKA, ARS, 90, 0, 1, 2, 0, None, "0.30", 0, 0, 0, 1, 4),
    (101, JESUS, ARS, 0, 0, 0, 0, 0, None, None, 0, 0, 0, 0, 0),
    (101, GABRIEL, ARS, 90, 0, 0, 1, 0, "0.10", "0.00", 1, 0, 2, 3, 0),
    (102, ROMERO, TOT, 90, 0, 0, 0, 0, "0.05", "0.00", 1, 0, 3, 4, 0),
    (301, ROMERO, TOT, 90, 0, 0, 1, 0, "0.10", "0.00", 1, 0, 2, 3, 0),
    (302, ROMERO, TOT, 90, 0, 0, 0, 0, "0.00", "0.00", 0, 1, 4, 2, 0),
    (102, MCGINN, AVL, 90, 1, 0, 2, 1, "0.30", "0.10", 1, 0, 2, 2, 1),
    (301, MCGINN, AVL, 80, 0, 1, 1, 0, "0.10", "0.20", 0, 0, 1, 1, 2),
    (102, WATKINS, AVL, 90, 0, 0, 3, 1, "0.60", "0.00", 0, 0, 0, 0, 1),
    (108, SOLANKE, TOT, 90, 2, 0, 5, 3, "1.10", "0.10", 0, 0, 1, 0, 1),
    (103, HAALAND, MCI, 90, 2, 0, 5, 4, "1.50", "0.00", 0, 0, 0, 0, 0),
]

# (team, player, status, reason, expected_return, source, updated_at)
AVAILABILITY = [
    (
        TOT,
        ROMERO,
        "injured",
        "Hamstring",
        date(2026, 10, 25),
        "api-football",
        datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
    ),
    (
        AVL,
        MCGINN,
        "suspended",
        "Red card",
        None,
        "api-football",
        datetime(2026, 10, 5, 18, 0, tzinfo=UTC),
    ),
    (
        ARS,
        SAKA,
        "doubtful",
        "Knock",
        None,
        "api-football",
        datetime(2026, 10, 6, 15, 0, tzinfo=UTC),
    ),
]

# (name, started_at, finished_at, status)
JOB_RUNS = [
    (
        "sync_availability",
        datetime(2026, 10, 7, 6, 0, tzinfo=UTC),
        AVAILABILITY_JOB_FINISHED,
        "success",
    ),
    (
        "sync_availability",
        datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 7, 9, 1, tzinfo=UTC),
        "failed",
    ),
]


# Odds for fixture 201 (Villa v Spurs): an earlier and a latest sweep, both inside 48h.
ODDS_EARLIER = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
ODDS_LATEST = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
ODDS_STALE = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
DISABLED_BOOKMAKER = "paddypower"

# (fixture, market, line, selection, bookmaker, price, captured_at)
ODDS = [
    (201, "h2h", None, "home", "skybet", "2.50", ODDS_EARLIER),
    (201, "h2h", None, "home", "coral", "2.30", ODDS_EARLIER),
    (201, "h2h", None, "draw", "skybet", "3.40", ODDS_EARLIER),
    (201, "h2h", None, "draw", "coral", "3.50", ODDS_EARLIER),
    (201, "h2h", None, "away", "skybet", "3.00", ODDS_EARLIER),
    (201, "h2h", None, "away", "coral", "3.10", ODDS_EARLIER),
    (201, "h2h", None, "home", "skybet", "2.20", ODDS_LATEST),
    (201, "h2h", None, "home", "coral", "2.25", ODDS_LATEST),
    (201, "h2h", None, "home", "williamhill", "2.10", ODDS_LATEST),
    (201, "h2h", None, "home", DISABLED_BOOKMAKER, "9.00", ODDS_LATEST),
    (201, "h2h", None, "draw", "skybet", "3.40", ODDS_LATEST),
    (201, "h2h", None, "draw", "coral", "3.50", ODDS_LATEST),
    (201, "h2h", None, "draw", "williamhill", "3.30", ODDS_LATEST),
    (201, "h2h", None, "away", "skybet", "3.20", ODDS_LATEST),
    (201, "h2h", None, "away", "coral", "3.10", ODDS_LATEST),
    (201, "h2h", None, "away", "williamhill", "3.30", ODDS_LATEST),
    (201, "totals", "2.5", "over", "skybet", "1.80", ODDS_LATEST),
    (201, "totals", "2.5", "over", "coral", "1.85", ODDS_LATEST),
    (201, "totals", "2.5", "under", "skybet", "2.00", ODDS_LATEST),
    (201, "totals", "2.5", "under", "coral", "1.95", ODDS_LATEST),
    (202, "h2h", None, "home", "skybet", "2.60", ODDS_STALE),
    (202, "h2h", None, "draw", "skybet", "3.30", ODDS_STALE),
    (202, "h2h", None, "away", "skybet", "2.80", ODDS_STALE),
]


def team_xg(goals: int) -> Decimal:
    """Deterministic xG for seeded team rows, so tests can compute expected totals."""
    return (Decimal(goals) * Decimal("0.9") + Decimal("0.3")).quantize(Decimal("0.01"))


def _team_rows() -> list[tuple]:
    rows = []
    for fid, _, _, _, home, away, _, status, hs, as_ in FIXTURES:
        if status != "finished":
            continue
        fetched = STALE_FETCHED if fid in STALE_FIXTURES else STATS_FETCHED
        has_xg = fid not in NO_XG_FIXTURES
        away_red = 1 if fid == 302 else 0
        for team, venue, gf, ga, corners, yellow, red in (
            (home, "home", hs, as_, 6, 2, 0),
            (away, "away", as_, hs, 4, 3, away_red),
        ):
            rows.append(
                (
                    fid,
                    team,
                    venue,
                    gf,
                    ga,
                    team_xg(gf) if has_xg else None,
                    team_xg(ga) if has_xg else None,
                    corners,
                    yellow,
                    red,
                    fetched,
                )
            )
    return rows


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


async def seed(conn: asyncpg.Connection) -> None:
    await conn.executemany(
        "INSERT INTO teams (id, provider_id, name, short_name, aliases, fetched_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        [(*t, STATS_FETCHED) for t in TEAMS],
    )
    await conn.executemany(
        "INSERT INTO players (id, provider_id, team_id, name, position, aliases, fetched_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        [(*p, STATS_FETCHED) for p in PLAYERS],
    )
    aliases = [
        (ALIAS_DISPLAY.get(a, a), a, "team", tid) for tid, *_, names in TEAMS for a in names
    ] + [(ALIAS_DISPLAY.get(a, a), a, "player", pid) for pid, *_, names in PLAYERS for a in names]
    await conn.executemany(
        "INSERT INTO entity_aliases (alias, alias_search, entity_type, entity_id)"
        " VALUES ($1, $2, $3, $4)",
        aliases,
    )
    await conn.executemany(
        "INSERT INTO fixtures (id, provider_id, season, matchweek, home_id, away_id, kickoff_at,"
        " status, home_score, away_score, fetched_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        [(*f, SCHEDULE_FETCHED if f[7] == "scheduled" else STATS_FETCHED) for f in FIXTURES],
    )
    await conn.executemany(
        "INSERT INTO team_match_stats (fixture_id, team_id, venue, goals_for, goals_against,"
        " xg_for, xg_against, corners, yellow_cards, red_cards, fetched_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        _team_rows(),
    )
    await conn.executemany(
        "INSERT INTO player_match_stats (fixture_id, player_id, team_id, minutes, goals, assists,"
        " shots, shots_on_target, xg, xa, yellow_cards, red_cards, fouls, tackles, key_passes,"
        " fetched_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)",
        [
            (
                *r[:8],
                _dec(r[8]),
                _dec(r[9]),
                *r[10:],
                STALE_FETCHED if r[0] in STALE_FIXTURES else STATS_FETCHED,
            )
            for r in PLAYER_ROWS
        ],
    )
    await conn.executemany(
        "INSERT INTO availability (team_id, player_id, status, reason, expected_return, source,"
        " updated_at, fetched_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        [(*a, AVAILABILITY_FETCHED) for a in AVAILABILITY],
    )
    await conn.executemany(
        "INSERT INTO job_runs (name, started_at, finished_at, status) VALUES ($1, $2, $3, $4)",
        JOB_RUNS,
    )
    await conn.execute(
        "UPDATE bookmakers SET is_enabled = false WHERE key = $1", DISABLED_BOOKMAKER
    )
    await conn.executemany(
        "INSERT INTO odds_snapshots (fixture_id, market, line, selection, bookmaker, price,"
        " captured_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        [
            (f, m, _dec(line), sel, bm, Decimal(price), at)
            for f, m, line, sel, bm, price, at in ODDS
        ],
    )
