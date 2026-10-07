from datetime import UTC, datetime, timedelta

import pytest

from oddsmith_ingestion.schedule import ScheduleState, due_jobs, load_state

# Tuesday 6 Oct 2026, 12:00 UTC (13:00 in London, BST)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
ALL_FRESH = {
    "seed_reference": NOW - timedelta(days=1),
    "sync_fixtures": NOW - timedelta(hours=1),  # after today's 06:00 London run time
    "sync_results": NOW - timedelta(minutes=5),
    "sync_availability": NOW - timedelta(minutes=5),
    "sync_odds": NOW - timedelta(minutes=5),
    "sync_btts": NOW - timedelta(minutes=5),
}


def state(last=None, next_kickoff=None, results_pending=False, now=NOW, success=None):
    attempts = ALL_FRESH if last is None else last
    return ScheduleState(
        now=now,
        last_attempt=attempts,
        last_success=attempts if success is None else success,
        next_kickoff=next_kickoff,
        results_pending=results_pending,
    )


def with_last(**ages):
    return {**ALL_FRESH, **{job: NOW - age for job, age in ages.items()}}


def test_everything_due_on_first_run_except_results_with_nothing_pending():
    assert due_jobs(state(last={})) == [
        "seed_reference",
        "sync_fixtures",
        "sync_availability",
        "sync_odds",
    ]


def test_nothing_due_when_everything_is_fresh():
    assert due_jobs(state()) == []


def test_seed_reference_weekly():
    assert "seed_reference" in due_jobs(state(with_last(seed_reference=timedelta(days=7))))
    assert "seed_reference" not in due_jobs(state(with_last(seed_reference=timedelta(days=6))))


def test_sync_fixtures_once_a_day_after_six_london_time():
    # Last ran yesterday at 07:00 London -> due today (it's 13:00 London)
    yesterday = state(with_last(sync_fixtures=timedelta(hours=30)))
    assert "sync_fixtures" in due_jobs(yesterday)
    # 05:30 London (04:30 UTC): today's 06:00 hasn't come yet, yesterday's run counts
    early = datetime(2026, 10, 6, 4, 30, tzinfo=UTC)
    last = {**ALL_FRESH, "sync_fixtures": datetime(2026, 10, 5, 5, 10, tzinfo=UTC)}
    assert "sync_fixtures" not in due_jobs(state(last, now=early))


@pytest.mark.parametrize(
    ("kickoff_in", "age", "due"),
    [
        (timedelta(days=3), timedelta(hours=5), False),  # 6h cadence away from matchday
        (timedelta(days=3), timedelta(hours=6), True),
        (timedelta(hours=20), timedelta(minutes=58), True),  # hourly within 24h (tick slack)
        (timedelta(hours=20), timedelta(minutes=40), False),
    ],
)
def test_availability_cadence(kickoff_in, age, due):
    s = state(with_last(sync_availability=age), next_kickoff=NOW + kickoff_in)
    assert ("sync_availability" in due_jobs(s)) is due


@pytest.mark.parametrize(
    ("kickoff_in", "age", "due"),
    [
        (timedelta(days=3), timedelta(minutes=90), False),  # every 2h normally
        (timedelta(days=3), timedelta(hours=2), True),
        (timedelta(hours=10), timedelta(minutes=29), True),  # every 30 min within 24h
        (None, timedelta(hours=3), True),
    ],
)
def test_odds_cadence(kickoff_in, age, due):
    s = state(with_last(sync_odds=age), next_kickoff=NOW + kickoff_in if kickoff_in else None)
    assert ("sync_odds" in due_jobs(s)) is due


def test_btts_every_two_hours_only_within_48_hours_of_a_kickoff():
    soon, later = NOW + timedelta(hours=30), NOW + timedelta(days=4)
    assert "sync_btts" in due_jobs(state(with_last(sync_btts=timedelta(hours=2)), soon))
    assert "sync_btts" not in due_jobs(state(with_last(sync_btts=timedelta(hours=1)), soon))
    assert "sync_btts" not in due_jobs(state(with_last(sync_btts=timedelta(hours=9)), later))


def test_results_every_30_minutes_while_pending():
    pending = state(with_last(sync_results=timedelta(minutes=30)), results_pending=True)
    assert "sync_results" in due_jobs(pending)
    idle = state(with_last(sync_results=timedelta(hours=5)), results_pending=False)
    assert "sync_results" not in due_jobs(idle)


async def test_load_state_reads_job_runs_and_fixtures(db):
    await db.execute(
        "INSERT INTO job_runs (name, status, started_at) VALUES "
        "('sync_odds', 'failed', $1), ('sync_odds', 'success', $2)",
        NOW - timedelta(hours=1),
        NOW - timedelta(hours=3),
    )
    s = await load_state(db, season=2026, now=NOW)
    assert s.last_attempt == {"sync_odds": NOW - timedelta(hours=1)}  # failures count
    assert s.last_success == {"sync_odds": NOW - timedelta(hours=3)}
    assert s.next_kickoff is None
    assert s.results_pending is False


def test_failed_sync_fixtures_is_retried_the_same_day():
    failed_today = state(success={**ALL_FRESH, "sync_fixtures": NOW - timedelta(hours=30)})
    assert "sync_fixtures" in due_jobs(failed_today)
