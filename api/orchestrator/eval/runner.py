"""Runs eval questions through the real answer loop and grades what comes back."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg

from orchestrator.cards import ToolOutcome
from orchestrator.config import OrchestratorSettings
from orchestrator.eval.cost import answer_cost, counted_tokens
from orchestrator.eval.grading import Finding, as_dicts, grade, passed
from orchestrator.eval.oracle import verify
from orchestrator.eval.questions import Question
from orchestrator.eval.recording import RecordingModel, skipped_calls
from orchestrator.loop import AnswerDeps, run_answer
from orchestrator.model_client import ModelClient
from orchestrator.routing import choose_model

logger = logging.getLogger(__name__)

Connect = Callable[[], AbstractAsyncContextManager[asyncpg.Connection]]
# (record, asked_at) -> (the judge's claims, its finding); None runs without a judge.
Judge = Callable[[Mapping[str, Any], datetime], Awaitable[tuple[list[dict[str, str]], Finding]]]


@dataclass(frozen=True)
class EvalDeps:
    model: ModelClient
    connect: Connect  # one read-only snapshot connection per question
    settings: OrchestratorSettings
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    judge: Judge | None = None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _of_type(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [e for e in events if e["type"] == kind]


async def _oracle_problems(
    conn: asyncpg.Connection, now: datetime, calls: list[dict[str, Any]]
) -> list[str]:
    problems: list[str] = []
    for call in calls:
        if call["skipped"]:
            continue
        found = await verify(conn, now, call)
        problems = [*problems, *(f"{call['name']} {call['input']}: {p}" for p in found)]
    return problems


async def _answer(
    question: Question, deps: EvalDeps, conn: asyncpg.Connection, now: datetime
) -> dict[str, Any]:
    """Ask one question and record everything the answer was built from."""

    @asynccontextmanager
    async def held():
        yield conn

    recording = RecordingModel(deps.model)
    outcomes: list[ToolOutcome] = []
    answer_deps = AnswerDeps(
        model=recording,
        connection=held,
        settings=deps.settings,
        clock=lambda: now,
        on_tool_call=outcomes.append,
    )
    started = time.perf_counter()
    events = [e async for e in run_answer(answer_deps, list(question.history), question.question)]
    duration = time.perf_counter() - started

    errors = _of_type(events, "error")
    usage_events = _of_type(events, "usage")
    calls = [
        *(
            {"name": o.name, "input": o.input, "result": o.result, "skipped": False}
            for o in outcomes
        ),
        *(skipped_calls(recording.requests[-1].messages) if recording.requests else []),
    ]
    usage = recording.total_usage
    model = (
        usage_events[0]["model"]
        if usage_events
        else choose_model(
            question.question, fast=deps.settings.model_fast, strong=deps.settings.model_strong
        )
    )
    return {
        "id": question.id,
        "category": question.category,
        "question": question.question,
        "history": [dict(turn) for turn in question.history],
        "asked_at": _iso(now),
        "model": model,
        "text": "".join(e["text"] for e in _of_type(events, "text_delta")),
        "cards": [e["card"] for e in _of_type(events, "card")],
        "sources": [s for e in _of_type(events, "sources") for s in e["sources"]],
        "error": errors[0]["error"]["message"] if errors else None,
        "tool_calls": calls,
        "turns": [asdict(u) for u in recording.usages],
        "usage": asdict(usage),
        "counted_tokens": counted_tokens(usage),
        "cost_usd": answer_cost(model, usage),
        "duration_s": round(duration, 1),
        "oracle": await _oracle_problems(conn, now, calls),
    }


async def run_question(question: Question, deps: EvalDeps) -> dict[str, Any]:
    """One graded record. A crash while answering is recorded as a failed question."""
    now = deps.clock()
    models = {"fast": deps.settings.model_fast, "strong": deps.settings.model_strong}
    try:
        async with deps.connect() as conn:
            record = await _answer(question, deps, conn, now)
    except Exception as error:
        logger.exception("question %s crashed", question.id)
        crash = Finding("answered", False, f"{type(error).__name__}: {error}")
        return {
            "id": question.id,
            "category": question.category,
            "question": question.question,
            "asked_at": _iso(now),
            "findings": as_dicts([crash]),
            "passed": False,
        }
    findings, figures = grade(question, record, now=now, models=models)
    claims: list[dict[str, str]] = []
    if deps.judge is not None:
        claims, verdict = await deps.judge(record, now)
        findings = [*findings, verdict]
    return {
        **record,
        "figures": figures,
        "judge_claims": claims,
        "findings": as_dicts(findings),
        "passed": passed(findings),
    }


async def run_eval(
    questions: Sequence[Question],
    deps: EvalDeps,
    *,
    concurrency: int,
    on_done: Callable[[dict[str, Any]], None] = lambda record: None,
) -> dict[str, Any]:
    """Run the questions, at most `concurrency` at a time; records keep the set's order."""
    gate = asyncio.Semaphore(concurrency)
    started = deps.clock()

    async def one(question: Question) -> dict[str, Any]:
        async with gate:
            record = await run_question(question, deps)
        on_done(record)
        return record

    records = await asyncio.gather(*(one(q) for q in questions))
    return {
        "started_at": _iso(started),
        "finished_at": _iso(deps.clock()),
        "models": {"fast": deps.settings.model_fast, "strong": deps.settings.model_strong},
        "judged": deps.judge is not None,
        "records": list(records),
    }
