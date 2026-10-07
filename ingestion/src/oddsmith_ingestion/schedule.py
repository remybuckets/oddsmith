"""When each job runs. A cron calls `tick` every 30 minutes; it runs whatever is due.

Cadence (SPEC "Ingestion jobs"), measured from each job's last attempt in job_runs:
  seed_reference     weekly
  sync_fixtures      daily, after 06:00 UK time (retried each tick until it succeeds)
  sync_results       every 30 min while any kicked-off fixture still lacks results
  sync_availability  every 6h; hourly within 24h of a kick-off
  sync_odds          every 2h; every 30 min within 24h of a kick-off
  sync_btts          every 2h within 48h of a kick-off (1 credit per match)
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import asyncpg

from oddsmith_ingestion import mapping
from oddsmith_ingestion.jobs.sync_results import DEFAULT_WINDOW, pending_fixture_ids

UK = ZoneInfo("Europe/London")
FIXTURES_RUN_AT = time(6, 0)
# Cron ticks drift by seconds to minutes; a job counts as due slightly early.
TICK_SLACK = timedelta(minutes=5)
MATCHDAY = timedelta(hours=24)
BTTS_WINDOW = timedelta(hours=48)
JOB_ORDER = (
    "seed_reference",
    "sync_fixtures",
    "sync_results",
    "sync_availability",
    "sync_odds",
    "sync_btts",
)


@dataclass(frozen=True)
class ScheduleState:
    now: datetime
    last_attempt: dict[str, datetime]
    last_success: dict[str, datetime]
    next_kickoff: datetime | None
    results_pending: bool


def due_jobs(state: ScheduleState) -> list[str]:
    checks = {
        "seed_reference": lambda: _older_than(state, "seed_reference", timedelta(days=7)),
        "sync_fixtures": lambda: _fixtures_due(state),
        "sync_results": lambda: (
            state.results_pending and _older_than(state, "sync_results", timedelta(minutes=30))
        ),
        "sync_availability": lambda: _older_than(
            state,
            "sync_availability",
            timedelta(hours=1) if _kickoff_within(state, MATCHDAY) else timedelta(hours=6),
        ),
        "sync_odds": lambda: _older_than(
            state,
            "sync_odds",
            timedelta(minutes=30) if _kickoff_within(state, MATCHDAY) else timedelta(hours=2),
        ),
        "sync_btts": lambda: (
            _kickoff_within(state, BTTS_WINDOW)
            and _older_than(state, "sync_btts", timedelta(hours=2))
        ),
    }
    return [job for job in JOB_ORDER if checks[job]()]


async def load_state(pool: asyncpg.Pool, *, season: int, now: datetime) -> ScheduleState:
    async with pool.acquire() as conn:
        runs = await conn.fetch(
            """SELECT name, max(started_at) AS last,
                      max(started_at) FILTER (WHERE status = 'success') AS last_success
               FROM job_runs GROUP BY name"""
        )
        next_kickoff = await conn.fetchval(
            """SELECT min(kickoff_at) FROM fixtures
               WHERE season = $1 AND status = 'scheduled' AND kickoff_at > $2""",
            mapping.season_label(season),
            now,
        )
        pending = await pending_fixture_ids(conn, season, now, DEFAULT_WINDOW)
    return ScheduleState(
        now=now,
        last_attempt={r["name"]: r["last"] for r in runs},
        last_success={r["name"]: r["last_success"] for r in runs if r["last_success"]},
        next_kickoff=next_kickoff,
        results_pending=bool(pending),
    )


def _older_than(state: ScheduleState, job: str, interval: timedelta) -> bool:
    last = state.last_attempt.get(job)
    return last is None or state.now - last >= interval - TICK_SLACK


def _kickoff_within(state: ScheduleState, horizon: timedelta) -> bool:
    return state.next_kickoff is not None and state.next_kickoff - state.now <= horizon


def _fixtures_due(state: ScheduleState) -> bool:
    local_now = state.now.astimezone(UK)
    run_at = datetime.combine(local_now.date(), FIXTURES_RUN_AT, tzinfo=UK)
    if local_now < run_at:
        run_at -= timedelta(days=1)
    # Measured from the last success, so a failed daily run is retried on the next tick.
    last = state.last_success.get("sync_fixtures")
    return last is None or last < run_at
