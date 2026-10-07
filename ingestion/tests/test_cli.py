from datetime import UTC, datetime

import pytest

from oddsmith_ingestion import cli


def test_parses_job_and_flags():
    args = cli.parse_args(["seed_reference", "--no-full-names"])
    assert args.job == "seed_reference"
    assert args.full_names is False


def test_full_names_default_on():
    assert cli.parse_args(["seed_reference"]).full_names is True


def test_rejects_unknown_job():
    with pytest.raises(SystemExit):
        cli.parse_args(["drop_everything"])


def test_season_override():
    assert cli.parse_args(["backfill_season", "--season", "2025"]).season == 2025
    assert cli.parse_args(["sync_fixtures"]).season is None


def make_ctx(pool=None):
    return cli.Context(pool=pool, api_football=None, odds_api=None, season=2026)


def test_every_job_has_a_runner_and_tick_exists():
    assert set(cli.JOBS) == {*cli.RUNNERS, "tick"}
    assert {"sync_availability", "sync_odds", "sync_btts"} <= set(cli.RUNNERS)


async def test_tick_runs_due_jobs_and_continues_past_failures(db, monkeypatch):
    calls = []

    async def ok(ctx):
        calls.append("ok")
        return 1

    async def boom(ctx):
        calls.append("boom")
        raise RuntimeError("provider down")

    monkeypatch.setattr(cli, "due_jobs", lambda state: ["sync_fixtures", "sync_odds"])
    monkeypatch.setattr(cli, "RUNNERS", {"sync_fixtures": boom, "sync_odds": ok})

    failed = await cli.tick(make_ctx(db), datetime(2026, 10, 6, tzinfo=UTC))

    assert calls == ["boom", "ok"]
    assert failed == ["sync_fixtures"]


async def test_tick_skips_when_another_tick_holds_the_lock(db, monkeypatch):
    calls = []

    async def ok(ctx):
        calls.append("ok")
        return 1

    monkeypatch.setattr(cli, "due_jobs", lambda state: ["sync_odds"])
    monkeypatch.setattr(cli, "RUNNERS", {"sync_odds": ok})
    async with db.acquire() as holder:
        await holder.execute("SELECT pg_advisory_lock($1)", cli.TICK_LOCK_ID)
        try:
            failed = await cli.tick(make_ctx(db), datetime(2026, 10, 6, tzinfo=UTC))
        finally:
            await holder.execute("SELECT pg_advisory_unlock($1)", cli.TICK_LOCK_ID)
    assert calls == []
    assert failed == []
