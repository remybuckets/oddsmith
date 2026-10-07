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
