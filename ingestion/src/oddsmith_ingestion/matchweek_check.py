"""Read-only health check of one matchweek's data: `cli check` (no provider calls).

Before kick-off: odds present, complete (h2h home/draw/away) and fresh; availability fresh.
From kick-off + RESULT_GRACE: finished, scored, team + player stats written and consistent.
Any failed job run in the last day is reported too.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import asyncpg

from oddsmith_ingestion import mapping

RESULT_GRACE = timedelta(hours=3)  # sync_results starts at kick-off + 2h; allow one more hour
ODDS_MAX_AGE = timedelta(hours=6)  # the orchestrator's staleness limit for odds
AVAILABILITY_MAX_AGE = timedelta(hours=24)  # and for availability
FAILED_RUN_LOOKBACK = timedelta(hours=24)
MIN_PLAYER_ROWS = 22  # 11 starters a side
LOOKBACK = timedelta(days=4)  # a matchweek spans Fri-Mon


@dataclass(frozen=True)
class Problem:
    fixture: str | None
    check: str
    detail: str


@dataclass(frozen=True)
class FixtureLine:
    label: str
    kickoff_at: datetime
    status: str
    score: str
    odds_captured_at: datetime | None
    bookmakers: int


@dataclass(frozen=True)
class Report:
    matchweek: int | None
    now: datetime
    fixtures: list[FixtureLine]
    problems: list[Problem]


async def current_matchweek(conn: asyncpg.Connection, season: int, now: datetime) -> int | None:
    """The matchweek in play or next: that of the earliest fixture from LOOKBACK ago on."""
    return await conn.fetchval(
        """SELECT matchweek FROM fixtures WHERE season = $1 AND kickoff_at >= $2
           AND matchweek IS NOT NULL ORDER BY kickoff_at LIMIT 1""",
        mapping.season_label(season),
        now - LOOKBACK,
    )


async def check_matchweek(
    pool: asyncpg.Pool, *, season: int, now: datetime, matchweek: int | None = None
) -> Report:
    async with pool.acquire() as conn:
        mw = matchweek or await current_matchweek(conn, season, now)
        rows = await conn.fetch(_FIXTURES_SQL, mapping.season_label(season), mw)
        jobs = await _job_problems(conn, now, any(r["kickoff_at"] > now for r in rows))
    fixtures = [
        FixtureLine(r["label"], r["kickoff_at"], r["status"], _score(r), r["odds_at"], r["books"])
        for r in rows
    ]
    problems = [p for r in rows for p in _fixture_problems(r, now)]
    return Report(mw, now, fixtures, [*problems, *jobs])


def _fixture_problems(r: asyncpg.Record, now: datetime) -> list[Problem]:
    label = r["label"]
    if r["status"] in ("postponed", "cancelled"):
        return []
    if r["kickoff_at"] > now:
        if r["odds_at"] is None:
            return [Problem(label, "odds_missing", "no odds captured")]
        found = []
        if now - r["odds_at"] > ODDS_MAX_AGE:
            found.append(Problem(label, "odds_stale", f"latest odds {_age(now, r['odds_at'])} old"))
        if not r["h2h_complete"]:
            found.append(Problem(label, "odds_incomplete", "no bookmaker has home/draw/away"))
        return found
    if now - r["kickoff_at"] < RESULT_GRACE:
        return []  # in play, or results not due yet
    if r["status"] != "finished" or r["home_score"] is None:
        return [
            Problem(
                label,
                "result_overdue",
                f"status {r['status']} at {_age(now, r['kickoff_at'])} after kick-off",
            )
        ]
    return _result_problems(r)


def _result_problems(r: asyncpg.Record) -> list[Problem]:
    label = r["label"]
    if r["team_rows"] != 2:
        return [Problem(label, "team_stats_missing", f"{r['team_rows']} team stat rows")]
    found = []
    if r["player_rows"] < MIN_PLAYER_ROWS:
        found.append(Problem(label, "player_stats_thin", f"{r['player_rows']} player rows"))
    if r["home_goals"] != r["home_score"] or r["away_goals"] != r["away_score"]:
        found.append(
            Problem(
                label,
                "score_mismatch",
                f"fixture {_score(r)}, team stats {r['home_goals']}-{r['away_goals']}",
            )
        )
    if r["xg_missing"]:
        found.append(Problem(label, "xg_missing", "team xG not provided"))
    return found


async def _job_problems(conn: asyncpg.Connection, now: datetime, upcoming: bool) -> list[Problem]:
    failed = await conn.fetch(
        """SELECT name, started_at, error FROM job_runs
           WHERE status = 'failed' AND started_at >= $1 ORDER BY started_at""",
        now - FAILED_RUN_LOOKBACK,
    )
    found = [
        Problem(None, "job_failed", f"{r['name']} at {r['started_at']:%a %H:%M} UTC: {r['error']}")
        for r in failed
    ]
    if upcoming:
        last = await conn.fetchval(
            "SELECT max(started_at) FROM job_runs WHERE name = 'sync_availability' "
            "AND status = 'success'"
        )
        if last is None or now - last > AVAILABILITY_MAX_AGE:
            age = "never run" if last is None else f"last success {_age(now, last)} ago"
            found.append(Problem(None, "availability_stale", age))
    return found


def _score(r: asyncpg.Record) -> str:
    return "" if r["home_score"] is None else f"{r['home_score']}-{r['away_score']}"


def _age(now: datetime, then: datetime) -> str:
    minutes = int((now - then).total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}m"


def format_report(report: Report) -> str:
    lines = [f"Matchweek {report.matchweek} at {report.now:%Y-%m-%d %H:%M} UTC"]
    for f in report.fixtures:
        odds = (
            f"odds {f.odds_captured_at:%a %H:%M} ({f.bookmakers} books)"
            if f.odds_captured_at
            else "no odds"
        )
        lines.append(
            f"  {f.kickoff_at:%a %d %H:%M}  {f.label:<34} {f.status:<10} {f.score:<5} {odds}"
        )
    lines.append(f"{len(report.problems)} problem(s)")
    lines += [f"  [{p.check}] {p.fixture or 'jobs'}: {p.detail}" for p in report.problems]
    return "\n".join(lines)


_FIXTURES_SQL = """
SELECT f.id, h.name || ' v ' || a.name AS label, f.kickoff_at, f.status,
       f.home_score, f.away_score,
       (SELECT max(captured_at) FROM odds_snapshots o WHERE o.fixture_id = f.id) AS odds_at,
       (SELECT count(DISTINCT bookmaker) FROM odds_latest o WHERE o.fixture_id = f.id) AS books,
       EXISTS (SELECT 1 FROM odds_latest o WHERE o.fixture_id = f.id AND o.market = 'h2h'
               GROUP BY o.bookmaker HAVING count(DISTINCT o.selection) = 3) AS h2h_complete,
       (SELECT count(*) FROM team_match_stats t WHERE t.fixture_id = f.id) AS team_rows,
       (SELECT count(*) FROM player_match_stats p WHERE p.fixture_id = f.id) AS player_rows,
       (SELECT goals_for FROM team_match_stats t
        WHERE t.fixture_id = f.id AND t.venue = 'home') AS home_goals,
       (SELECT goals_for FROM team_match_stats t
        WHERE t.fixture_id = f.id AND t.venue = 'away') AS away_goals,
       EXISTS (SELECT 1 FROM team_match_stats t
               WHERE t.fixture_id = f.id AND t.xg_for IS NULL) AS xg_missing
FROM fixtures f JOIN teams h ON h.id = f.home_id JOIN teams a ON a.id = f.away_id
WHERE f.season = $1 AND f.matchweek = $2
ORDER BY f.kickoff_at, f.id
"""
