from contextlib import asynccontextmanager

import anthropic
import httpx2
import pytest

from orchestrator.config import OrchestratorSettings
from orchestrator.loop import MAX_TOOL_CALLS, AnswerDeps, run_answer
from orchestrator.tests.fake_model import Scripted, ScriptedModel, tool_use
from orchestrator.tests.openapi import assert_stream_events
from orchestrator.tests.seed import NOW

pytestmark = pytest.mark.asyncio

SETTINGS = OrchestratorSettings(
    model_fast="claude-sonnet-5-5",
    model_strong="claude-opus-5-5",
    news_enabled=False,
    value_edge_threshold=0.05,
)


def deps_for(conn, model):
    @asynccontextmanager
    async def connection():
        yield conn

    return AnswerDeps(model=model, connection=connection, settings=SETTINGS, clock=lambda: NOW)


async def collect(deps, question="Best price on Villa v Spurs?", history=()):
    return [event async for event in run_answer(deps, list(history), question)]


def of_type(events, kind):
    return [e for e in events if e["type"] == kind]


ODDS_SCRIPT = [
    Scripted(
        chunks=("Let me look that up.",),
        tool_uses=(
            tool_use("t1", "resolve_entity", query="Spurs"),
            tool_use("t2", "get_fixtures", team_id=3, opponent_team_id=2, status="scheduled"),
        ),
    ),
    Scripted(tool_uses=(tool_use("t3", "get_odds", fixture_id=201, market="h2h"),)),
    Scripted(chunks=("Villa are 2.25 ", "with Coral (The Odds API, 7 Oct 11:00).")),
]


async def test_answer_streams_events_in_contract_order(conn):
    events = await collect(deps_for(conn, ScriptedModel(ODDS_SCRIPT)))

    assert_stream_events(events)
    kinds = [e["type"] for e in events]
    assert kinds[-2:] == ["sources", "usage"]
    assert kinds.index("card") > max(i for i, k in enumerate(kinds) if k == "text_delta")
    assert "".join(e["text"] for e in of_type(events, "text_delta")) == (
        "Villa are 2.25 with Coral (The Odds API, 7 Oct 11:00)."
    )


async def test_preamble_before_the_first_tool_results_is_not_streamed(conn):
    events = await collect(deps_for(conn, ScriptedModel(ODDS_SCRIPT)))
    assert "Let me look that up." not in "".join(e["text"] for e in of_type(events, "text_delta"))


async def test_tool_status_brackets_each_call(conn):
    events = await collect(deps_for(conn, ScriptedModel(ODDS_SCRIPT)))

    statuses = [(e["tool"], e["status"]) for e in of_type(events, "tool_status")]
    assert statuses == [
        ("resolve_entity", "started"),
        ("resolve_entity", "finished"),
        ("get_fixtures", "started"),
        ("get_fixtures", "finished"),
        ("get_odds", "started"),
        ("get_odds", "finished"),
    ]
    assert of_type(events, "tool_status")[-1]["label"] == "Checking odds"


async def test_cards_and_sources_come_from_tool_results(conn):
    events = await collect(deps_for(conn, ScriptedModel(ODDS_SCRIPT)))

    (card,) = [e["card"] for e in of_type(events, "card")]
    assert card["card_type"] == "odds"
    (sources,) = of_type(events, "sources")
    assert {
        "source": "The Odds API",
        "as_of": "2026-10-07T10:00:00Z",
        "is_stale": False,
    } in sources["sources"]


async def test_usage_sums_tokens_and_records_every_tool_call(conn):
    events = await collect(deps_for(conn, ScriptedModel(ODDS_SCRIPT)))

    usage = events[-1]
    assert usage["model"] == "claude-sonnet-5-5"
    assert usage["tokens_in"] == 3 * (100 + 1000)  # uncached + cache reads, three turns
    assert usage["tokens_out"] == 3 * 20
    assert [c["tool"] for c in usage["tool_calls"]] == [
        "resolve_entity",
        "get_fixtures",
        "get_odds",
    ]
    odds_call = usage["tool_calls"][2]
    assert odds_call["input"] == {"fixture_id": 201, "market": "h2h"}
    assert (odds_call["source"], odds_call["as_of"], odds_call["is_stale"]) == (
        "The Odds API",
        "2026-10-07T10:00:00Z",
        False,
    )
    assert odds_call["error"] is None
    assert odds_call["duration_ms"] >= 0


async def test_tool_results_go_back_to_claude_in_one_message(conn):
    model = ScriptedModel(ODDS_SCRIPT)
    await collect(deps_for(conn, model))

    second = model.requests[1].messages
    assert second[-2]["role"] == "assistant"
    results = second[-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert all(r["type"] == "tool_result" and not r["is_error"] for r in results)


async def test_failed_tool_is_reported_and_makes_no_card(conn):
    model = ScriptedModel(
        [
            Scripted(tool_uses=(tool_use("t1", "get_odds", fixture_id=201, market="btts"),)),
            Scripted(chunks=("No BTTS prices yet.",)),
        ]
    )
    events = await collect(deps_for(conn, model))

    assert of_type(events, "tool_status")[-1]["status"] == "failed"
    assert of_type(events, "card") == []
    assert events[-1]["tool_calls"][0]["error"].startswith("No current both teams to score")
    assert model.requests[1].messages[-1]["content"][0]["is_error"] is True


async def test_no_tool_answer_is_still_streamed(conn):
    model = ScriptedModel([Scripted(chunks=("I only cover the Premier League.",))])
    events = await collect(deps_for(conn, model), question="Who wins the Ashes?")

    assert "".join(e["text"] for e in of_type(events, "text_delta")) == (
        "I only cover the Premier League."
    )
    assert of_type(events, "sources") == [{"type": "sources", "sources": []}]
    assert events[-1]["tool_calls"] == []


async def test_tool_calls_are_capped_and_claude_must_then_answer(conn):
    greedy = Scripted(
        tool_uses=(
            tool_use("a", "get_league_table"),
            tool_use("b", "get_league_table", venue="home"),
            tool_use("c", "get_league_table", venue="away"),
        )
    )
    model = ScriptedModel([greedy, greedy, greedy, Scripted(chunks=("Done.",))])
    events = await collect(deps_for(conn, model))

    assert len(events[-1]["tool_calls"]) == MAX_TOOL_CALLS
    assert [r.allow_tools for r in model.requests] == [True, True, True, False]
    refused = model.requests[3].messages[-1]["content"][-1]
    assert refused["is_error"] is True
    assert "limit" in refused["content"]


async def test_value_questions_route_to_the_strong_model(conn):
    model = ScriptedModel([Scripted(chunks=("Estimate only.",))])
    events = await collect(deps_for(conn, model), question="Is there value in Villa to win?")

    assert {r.model for r in model.requests} == {"claude-opus-5-5"}
    assert events[-1]["model"] == "claude-opus-5-5"


async def test_request_carries_cached_system_prompt_tools_and_history(conn):
    model = ScriptedModel([Scripted(chunks=("Hi.",))])
    history = [{"role": "user", "content": "Earlier?"}, {"role": "assistant", "content": "Yes."}]
    await collect(deps_for(conn, model), history=history)

    request = model.requests[0]
    assert request.system[0]["cache_control"] == {"type": "ephemeral"}
    assert "search_news" not in {t["name"] for t in request.tools}
    assert request.messages[:2] == history
    assert request.messages[2]["content"].startswith("Today is Wednesday 7 October 2026")


async def test_refusal_gives_a_polite_answer(conn):
    model = ScriptedModel([Scripted(stop_reason="refusal")])
    events = await collect(deps_for(conn, model))

    assert of_type(events, "text_delta")[0]["text"].startswith("Sorry")
    assert events[-1]["type"] == "usage"


async def test_api_failure_yields_one_error_and_stops(conn, caplog):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    model = ScriptedModel([], error=anthropic.APIConnectionError(request=request))
    events = await collect(deps_for(conn, model))

    assert events == [
        {
            "type": "error",
            "error": {
                "code": "internal",
                "message": "Oddsmith couldn't finish that answer. Please try again.",
            },
        }
    ]
    assert_stream_events(events)
    assert "answer failed" in caplog.text


async def test_truncated_answer_is_kept_and_logged(conn, caplog):
    model = ScriptedModel([Scripted(chunks=("Half an ans",), stop_reason="max_tokens")])
    events = await collect(deps_for(conn, model))

    assert of_type(events, "text_delta")[0]["text"] == "Half an ans"
    assert "max_tokens" in caplog.text
