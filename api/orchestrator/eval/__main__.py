"""Command line for the eval. `run` calls the Claude API and costs money; `sweep` does not.

    uv run python -m orchestrator.eval run --db-env-file ../.env.production
    uv run python -m orchestrator.eval run --only v01,p02 --no-judge
    uv run python -m orchestrator.eval sweep --db-env-file ../.env.production
    uv run python -m orchestrator.eval report orchestrator/eval/results/run-....json

The database comes from EVAL_DATABASE_URL, or DATABASE_URL in --db-env-file. It is only
ever read: see database.py.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import anthropic

from orchestrator.config import OrchestratorSettings
from orchestrator.eval.database import database_url, read_only_pool, snapshot
from orchestrator.eval.judge import judged
from orchestrator.eval.questions import CATEGORIES, load_questions, select
from orchestrator.eval.report import render
from orchestrator.eval.runner import EvalDeps, run_eval
from orchestrator.eval.sweep import run_sweep
from orchestrator.model_client import AnthropicModel

RESULTS_DIR = Path(__file__).with_name("results")
DEFAULT_CONCURRENCY = 4
DEFAULT_SWEEP_PLAYERS = 150


def _progress(record: dict[str, Any]) -> None:
    failed = ", ".join(f["check"] for f in record["findings"] if not f["ok"])
    status = "PASS" if record["passed"] else f"FAIL ({failed})"
    cost = f"${record.get('cost_usd', 0):.3f}"
    print(f"{record['id']:>4}  {status}  {record.get('duration_s', 0)}s  {cost}", flush=True)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _run(args: argparse.Namespace) -> int:
    settings = OrchestratorSettings()
    questions = select(
        load_questions(),
        ids=args.only.split(",") if args.only else None,
        categories=args.category,
    )
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    pool = await read_only_pool(database_url(args.db_env_file), args.concurrency)
    try:
        deps = EvalDeps(
            model=AnthropicModel(client),
            connect=partial(snapshot, pool),
            settings=settings,
            judge=None if args.no_judge else partial(judged, client, settings.model_strong),
        )
        run = await run_eval(questions, deps, concurrency=args.concurrency, on_done=_progress)
    finally:
        await pool.close()

    out = args.out or RESULTS_DIR / f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    _write(out, json.dumps(run, indent=1, ensure_ascii=False))
    _write(out.with_suffix(".md"), render(run))
    failed = sum(1 for r in run["records"] if not r["passed"])
    print(f"\n{len(run['records']) - failed} passed, {failed} failed. Results: {out}")
    return 1 if failed else 0


async def _sweep(args: argparse.Namespace) -> int:
    pool = await read_only_pool(database_url(args.db_env_file), 1)
    try:
        async with snapshot(pool) as conn:
            result = await run_sweep(conn, datetime.now(UTC), args.players)
    finally:
        await pool.close()
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 1 if result["problem_count"] else 0


def _report(args: argparse.Namespace) -> int:
    print(render(json.loads(args.results.read_text(encoding="utf-8"))))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.eval", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="ask the eval questions (calls the Claude API)")
    run.add_argument("--only", help="comma-separated question ids, e.g. p01,v03")
    run.add_argument("--category", action="append", choices=CATEGORIES)
    run.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    run.add_argument("--no-judge", action="store_true", help="skip the Claude judge pass")
    run.add_argument("--out", type=Path, help="results file (default: eval/results/run-*.json)")

    sweep = commands.add_parser("sweep", help="check every tool against SQL (no Claude)")
    sweep.add_argument("--players", type=int, default=DEFAULT_SWEEP_PLAYERS)

    for command in (run, sweep):
        command.add_argument("--db-env-file", type=Path, help="file holding DATABASE_URL")

    report = commands.add_parser("report", help="print a results file as Markdown")
    report.add_argument("results", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parser().parse_args(argv)
    if args.command == "report":
        return _report(args)
    try:
        return asyncio.run(_run(args) if args.command == "run" else _sweep(args))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
