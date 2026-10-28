"""The eval runner end to end on the seeded test database, with a scripted model."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from orchestrator.config import OrchestratorSettings
from orchestrator.eval.database import database_url
from orchestrator.eval.grading import Finding
from orchestrator.eval.questions import Question
from orchestrator.eval.recording import skipped_calls
from orchestrator.eval.report import render
from orchestrator.eval.runner import EvalDeps, run_eval, run_question
from orchestrator.eval.sweep import run_sweep
from orchestrator.loop import LIMIT_RESULT
from orchestrator.tests.fake_model import USAGE, Scripted, ScriptedModel, tool_use
from orchestrator.tests.seed import NOW

SETTINGS = OrchestratorSettings(
    model_fast="claude-sonnet-5-5",
    model_strong="claude-opus-5-5",
    news_enabled=False,
    value_edge_threshold=0.05,
)
QUESTION = Question.from_dict(
    {
        "id": "o01",
        "category": "odds",
        "question": "Best price on Villa v Spurs?",
        "expect": {"model": "fast", "tools": ["get_fixtures", "get_odds"]},
    }
)


def script(answer: str) -> list[Scripted]:
    return [
        Scripted(
            tool_uses=(
                tool_use("t1", "resolve_entity", query="Spurs"),
                tool_use("t2", "get_fixtures", team_id=3, opponent_team_id=2, status="scheduled"),
            )
        ),
        Scripted(tool_uses=(tool_use("t3", "get_odds", fixture_id=201, market="h2h"),)),
        Scripted(chunks=(answer,)),
    ]


class FreshScriptPerQuestion:
    """Replays the script from the top for each new conversation."""

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self._current = ScriptedModel(script(answer))

    def stream_turn(self, request):
        if not any(m["role"] == "assistant" for m in request.messages):
            self._current = ScriptedModel(script(self._answer))
        return self._current.stream_turn(request)


def deps_for(conn, answer, judge=None):
    @asynccontextmanager
    async def connect():
        yield conn

    return EvalDeps(
        model=FreshScriptPerQuestion(answer),
        connect=connect,
        settings=SETTINGS,
        clock=lambda: NOW,
        judge=judge,
    )


RIGHT = "Villa are 2.25 with Coral, the best price (The Odds API, 7 Oct 11:00)."
WRONG = "Villa are 2.75 with Coral, the best price (The Odds API, 7 Oct 11:00)."


def failed(record):
    return {f["check"] for f in record["findings"] if not f["ok"]}


async def test_a_right_answer_is_recorded_and_passes(conn):
    record = await run_question(QUESTION, deps_for(conn, RIGHT))

    assert record["passed"], record["findings"]
    assert record["text"] == RIGHT
    assert record["model"] == "claude-sonnet-5-5"
    assert [c["name"] for c in record["tool_calls"]] == [
        "resolve_entity",
        "get_fixtures",
        "get_odds",
    ]
    assert record["tool_calls"][2]["result"]["data"]["selections"][0]["best_price"] == 2.25
    assert record["oracle"] == []
    assert [c["card_type"] for c in record["cards"]] == ["odds"]
    assert record["figures"][0]["kind"] == "exact"


async def test_usage_is_recorded_per_turn_and_costed(conn):
    record = await run_question(QUESTION, deps_for(conn, RIGHT))

    assert len(record["turns"]) == 3
    assert record["usage"] == {
        "input_tokens": USAGE.input_tokens * 3,
        "output_tokens": USAGE.output_tokens * 3,
        "cache_read_tokens": USAGE.cache_read_tokens * 3,
        "cache_write_tokens": 0,
    }
    assert record["counted_tokens"] == 3 * (100 + 1000 + 20)
    # 300 input at $2/M, 60 output at $10/M, 3000 cache reads at $0.20/M.
    assert record["cost_usd"] == pytest.approx((300 * 2 + 60 * 10 + 3000 * 0.2) / 1e6)


async def test_a_wrong_figure_fails_the_question(conn):
    record = await run_question(QUESTION, deps_for(conn, WRONG))

    assert not record["passed"]
    assert failed(record) == {"figures"}


async def test_the_judge_verdict_is_part_of_the_grade(conn):
    async def judge(record, now):
        claims = [{"claim": "Villa 2.25", "verdict": "wrong", "reason": "it is Spurs' price"}]
        return claims, Finding("judge", False, "wrong: Villa 2.25")

    record = await run_question(QUESTION, deps_for(conn, RIGHT, judge=judge))

    assert failed(record) == {"judge"}
    assert record["judge_claims"][0]["verdict"] == "wrong"


async def test_a_crash_is_recorded_as_a_failed_question(conn):
    @asynccontextmanager
    async def broken():
        raise ConnectionError("database is down")
        yield

    deps = EvalDeps(
        model=ScriptedModel(script(RIGHT)), connect=broken, settings=SETTINGS, clock=lambda: NOW
    )

    record = await run_question(QUESTION, deps)

    assert not record["passed"]
    assert "database is down" in record["findings"][0]["detail"]


async def test_run_eval_keeps_question_order_and_reports(conn):
    second = Question.from_dict({**QUESTION.__dict__, "id": "o02", "history": []})
    done = []

    run = await run_eval(
        [QUESTION, second], deps_for(conn, RIGHT), concurrency=1, on_done=done.append
    )

    assert [r["id"] for r in run["records"]] == ["o01", "o02"]
    assert len(done) == 2
    assert run["models"] == {"fast": "claude-sonnet-5-5", "strong": "claude-opus-5-5"}
    json.dumps(run)  # the whole run must serialise

    report = render(run)
    assert "passed 2, failed 0" in report
    assert "| claude-sonnet-5-5 | 2 |" in report


async def test_the_report_shows_each_failure_with_its_answer(conn):
    run = await run_eval([QUESTION], deps_for(conn, WRONG), concurrency=1)

    report = render(run)

    assert "passed 0, failed 1" in report
    assert "**figures**: 2.75" in report
    assert f"> {WRONG}" in report


def test_skipped_calls_are_the_ones_refused_at_the_tool_cap():
    messages = [
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": [
                tool_use("a", "get_odds", fixture_id=1, market="h2h"),
                tool_use("b", "get_odds", fixture_id=2, market="h2h"),
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "a", "content": '{"ok": true}'},
                {"type": "tool_result", "tool_use_id": "b", "content": json.dumps(LIMIT_RESULT)},
            ],
        },
    ]

    calls = skipped_calls(messages)

    assert [(c["name"], c["input"]["fixture_id"], c["skipped"]) for c in calls] == [
        ("get_odds", 2, True)
    ]


async def test_sweep_finds_no_problems_on_the_seeded_database(conn):
    result = await run_sweep(conn, NOW, max_players=5)

    assert result["problems"] == []
    assert result["calls"] > 50
    assert result["by_tool"]["get_league_table"] == {"ok": 3}
    assert "get_odds" in result["by_tool"]
    assert "compare_to_market" in result["by_tool"]


def test_database_url_prefers_the_environment_then_the_env_file(tmp_path: Path):
    env_file = tmp_path / ".env.production"
    env_file.write_text("SUPABASE_URL=https://x\nDATABASE_URL=postgresql://file/db\n")

    assert database_url(env_file, {}) == "postgresql://file/db"
    assert database_url(env_file, {"EVAL_DATABASE_URL": "postgresql://env/db"}) == (
        "postgresql://env/db"
    )
    with pytest.raises(ValueError, match="EVAL_DATABASE_URL"):
        database_url(None, {})


def test_database_url_must_be_in_the_env_file(tmp_path: Path):
    env_file = tmp_path / ".env.production"
    env_file.write_text("SUPABASE_URL=https://x\n")

    with pytest.raises(ValueError, match="No DATABASE_URL"):
        database_url(env_file, {})
