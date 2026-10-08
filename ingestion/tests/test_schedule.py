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


# --- lean cadence (The Odds API free tier, ~300 credits/month) ---------------------------

SAT_MORNING = datetime(2026, 10, 10, 8, 30, tzinfo=UTC)  # 09:30 London
SAT_LATE = datetime(2026, 10, 10, 20, 30, tzinfo=UTC)  # 21:30 London
WEDNESDAY = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def lean(now, odds_age=None, btts_age=None, kickoff_today=True, next_kickoff_in=timedelta(hours=3)):
    last = {**{k: now - timedelta(minutes=1) for k in ALL_FRESH}}
    if odds_age is not None:
        last["sync_odds"] = now - odds_age
    if btts_age is not None:
        last["sync_btts"] = now - btts_age
    s = ScheduleState(
        now=now,
        last_attempt=last,
        last_success=last,
        next_kickoff=now + next_kickoff_in,
        results_pending=False,
        kickoff_today=kickoff_today,
    )
    return due_jobs(s, odds_cadence="lean")


def test_lean_odds_every_two_hours_in_the_matchday_window():
    assert "sync_odds" in lean(SAT_MORNING, odds_age=timedelta(hours=2))
    assert "sync_odds" not in lean(SAT_MORNING, odds_age=timedelta(minutes=45))


def test_lean_odds_not_refreshed_outside_08_to_20_uk():
    assert "sync_odds" not in lean(SAT_LATE, odds_age=timedelta(hours=3))


def test_lean_odds_daily_on_days_without_a_kickoff():
    days = timedelta(days=3)
    assert "sync_odds" not in lean(
        WEDNESDAY, odds_age=timedelta(hours=20), kickoff_today=False, next_kickoff_in=days
    )
    assert "sync_odds" in lean(
        WEDNESDAY, odds_age=timedelta(hours=24), kickoff_today=False, next_kickoff_in=days
    )


def test_lean_btts_once_on_matchday_morning():
    assert "sync_btts" in lean(SAT_MORNING, btts_age=timedelta(hours=20))
    assert "sync_btts" not in lean(SAT_MORNING, btts_age=timedelta(hours=1))  # already today
    assert "sync_btts" not in lean(
        WEDNESDAY,
        btts_age=timedelta(days=3),
        kickoff_today=False,
        next_kickoff_in=timedelta(days=3),
    )


def test_unknown_cadence_is_rejected():
    with pytest.raises(ValueError):
        due_jobs(state(), odds_cadence="turbo")


async def test_load_state_knows_whether_a_match_is_on_today_uk(db):
    from oddsmith_ingestion.repository import ensure_teams

    async with db.acquire() as conn:
        ids = await ensure_teams(conn, [{"id": 42, "name": "Arsenal"}, {"id": 63, "name": "Leeds"}])
    await db.execute(
        """INSERT INTO fixtures (provider_id, season, home_id, away_id, kickoff_at, status)
           VALUES (1, '2026/27', $1, $2, '2026-10-10 11:30+00', 'scheduled')""",
        ids[42],
        ids[63],
    )
    assert (await load_state(db, season=2026, now=SAT_MORNING)).kickoff_today is True
    assert (await load_state(db, season=2026, now=WEDNESDAY)).kickoff_today is False
