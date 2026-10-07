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


async def test_dispatch_routes_each_job(monkeypatch):
    called = []
    for name in ("seed_reference", "sync_fixtures", "sync_results", "backfill_season"):

        async def fake(pool, client, *, season, _name=name, **kw):
            called.append((_name, season))
            return 1

        monkeypatch.setattr(cli, name, fake)
    for job in cli.JOBS:
        await cli.dispatch(cli.parse_args([job]), pool=None, client=None, season=2026)
    assert called == [(job, 2026) for job in cli.JOBS]
