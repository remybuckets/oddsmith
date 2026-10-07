"""SSE answers: event order, what's forwarded, what's persisted."""

import uuid

from tests.sse import parse_sse

QUESTION = "How has Saka done away from home this season?"
TOOL_CALL = {
    "tool": "get_player_stats",
    "input": {"player_id": 7},
    "source": "API-Football",
    "as_of": "2026-10-10T09:00:00Z",
    "is_stale": False,
    "duration_ms": 40,
    "error": None,
}
SOURCE = {"source": "API-Football", "as_of": "2026-10-10T09:00:00Z", "is_stale": False}


def scripted(*events):
    async def _answer(history, question):
        for event in events:
            yield event

    return _answer


GOOD_ANSWER = scripted(
    {
        "type": "tool_status",
        "tool": "get_player_stats",
        "status": "started",
        "label": "Checking stats",
    },
    {"type": "text_delta", "text": "Saka has 3 goals "},
    {"type": "text_delta", "text": "away (API-Football, 10 Oct 10:00)."},
    {"type": "sources", "sources": [SOURCE]},
    {
        "type": "usage",
        "model": "claude-sonnet-5-5",
        "tokens_in": 900,
        "tokens_out": 100,
        "tool_calls": [TOOL_CALL],
    },
)


async def _conversation(http, user) -> str:
    return (await http.post("/conversations", headers=user.headers)).json()["data"]["id"]


async def _ask(http, user, conversation_id, content=QUESTION):
    response = await http.post(
        f"/conversations/{conversation_id}/messages",
        headers=user.headers,
        json={"content": content},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def test_stream_order_and_framing(with_deps, make_client, adult):
    async with make_client(with_deps(answer=GOOD_ANSWER)) as http:
        conversation_id = await _conversation(http, adult)
        events = await _ask(http, adult, conversation_id)

    names = [name for name, _ in events]
    assert names == [
        "message_start",
        "tool_status",
        "text_delta",
        "text_delta",
        "sources",
        "message_end",
    ]
    assert all(name == data["type"] for name, data in events)
    start, end = events[0][1], events[-1][1]
    assert start["conversation_id"] == conversation_id
    assert end["message_id"] == start["message_id"]
    assert end["questions_remaining"] == 14


async def test_usage_is_never_forwarded(with_deps, make_client, adult):
    async with make_client(with_deps(answer=GOOD_ANSWER)) as http:
        events = await _ask(http, adult, await _conversation(http, adult))

    assert "usage" not in [name for name, _ in events]


async def test_exchange_is_persisted(with_deps, make_client, pool, adult):
    async with make_client(with_deps(answer=GOOD_ANSWER)) as http:
        conversation_id = await _conversation(http, adult)
        events = await _ask(http, adult, conversation_id)
        listed = (
            await http.get(f"/conversations/{conversation_id}/messages", headers=adult.headers)
        ).json()["data"]

    assert [(m["role"], m["content"]) for m in listed] == [
        ("user", QUESTION),
        ("assistant", "Saka has 3 goals away (API-Football, 10 Oct 10:00)."),
    ]
    assert listed[1]["id"] == events[0][1]["message_id"]
    assert listed[1]["feedback"] is None
    row = await pool.fetchrow(
        "SELECT tool_calls, model, tokens_in, tokens_out FROM messages WHERE id = $1",
        uuid.UUID(listed[1]["id"]),
    )
    assert dict(row) == {
        "tool_calls": [TOOL_CALL],
        "model": "claude-sonnet-5-5",
        "tokens_in": 900,
        "tokens_out": 100,
    }


async def test_usage_daily_and_counters_are_updated(with_deps, make_client, pool, redis, adult):
    async with make_client(with_deps(answer=GOOD_ANSWER)) as http:
        conversation_id = await _conversation(http, adult)
        await _ask(http, adult, conversation_id)
        await _ask(http, adult, conversation_id)

    row = await pool.fetchrow(
        "SELECT date::text, questions, tokens_in, tokens_out FROM usage_daily WHERE user_id = $1",
        adult.id,
    )
    assert dict(row) == {"date": "2026-10-10", "questions": 2, "tokens_in": 1800, "tokens_out": 200}
    assert await redis.get(f"questions:2026-10-10:{adult.id}") == "2"
    assert await redis.get("tokens:2026-10-10") == "2000"


async def test_conversation_gets_title_and_moves_to_top(with_deps, make_client, adult):
    async with make_client(with_deps(answer=GOOD_ANSWER)) as http:
        older = await _conversation(http, adult)
        await _conversation(http, adult)
        await _ask(http, adult, older, content="x" * 200)
        listed = (await http.get("/conversations", headers=adult.headers)).json()["data"]

    assert listed[0]["id"] == older
    assert listed[0]["title"] == "x" * 80


async def test_history_is_passed_to_orchestrator(with_deps, make_client, adult):
    seen = []

    async def recording(history, question):
        seen.append((history, question))
        async for event in GOOD_ANSWER(history, question):
            yield event

    async with make_client(with_deps(answer=recording)) as http:
        conversation_id = await _conversation(http, adult)
        await _ask(http, adult, conversation_id, content="first")
        await _ask(http, adult, conversation_id, content="second")

    assert seen[0] == ([], "first")
    history, question = seen[1]
    assert question == "second"
    assert [turn["role"] for turn in history] == ["user", "assistant"]
    assert history[0]["content"] == "first"


async def test_orchestrator_error_event_replaces_rest_and_refunds(
    with_deps, make_client, pool, redis, adult
):
    failing = scripted(
        {"type": "text_delta", "text": "partial"},
        {"type": "error", "error": {"code": "internal", "message": "Claude 529 overloaded"}},
        {"type": "text_delta", "text": "never sent"},
    )
    async with make_client(with_deps(answer=failing)) as http:
        events = await _ask(http, adult, await _conversation(http, adult))

    assert [name for name, _ in events] == ["message_start", "text_delta", "error"]
    error = events[-1][1]["error"]
    assert error["code"] == "internal"
    assert "529" not in error["message"]
    assert await pool.fetchval("SELECT count(*) FROM messages") == 0
    assert await redis.get(f"questions:2026-10-10:{adult.id}") == "0"


async def test_orchestrator_exception_becomes_error_event(
    with_deps, make_client, pool, redis, adult
):
    async def exploding(history, question):
        yield {"type": "text_delta", "text": "partial"}
        raise RuntimeError("boom")

    async with make_client(with_deps(answer=exploding)) as http:
        events = await _ask(http, adult, await _conversation(http, adult))

    assert [name for name, _ in events] == ["message_start", "text_delta", "error"]
    assert await pool.fetchval("SELECT count(*) FROM usage_daily") == 0
    assert await redis.get(f"questions:2026-10-10:{adult.id}") == "0"


async def test_unknown_event_types_are_dropped(with_deps, make_client, adult):
    leaky = scripted(
        {"type": "tool_result", "raw": {"secret": 1}},
        {"type": "text_delta", "text": "ok"},
        {"type": "sources", "sources": []},
        {"type": "usage", "model": "m", "tokens_in": 1, "tokens_out": 1, "tool_calls": []},
    )
    async with make_client(with_deps(answer=leaky)) as http:
        events = await _ask(http, adult, await _conversation(http, adult))

    assert [name for name, _ in events] == ["message_start", "text_delta", "sources", "message_end"]


async def test_missing_usage_still_persists_answer(with_deps, make_client, pool, adult):
    no_usage = scripted({"type": "text_delta", "text": "ok"}, {"type": "sources", "sources": []})
    async with make_client(with_deps(answer=no_usage)) as http:
        events = await _ask(http, adult, await _conversation(http, adult))

    assert events[-1][0] == "message_end"
    row = await pool.fetchrow("SELECT tokens_in, tool_calls FROM messages WHERE role='assistant'")
    assert dict(row) == {"tokens_in": 0, "tool_calls": []}


async def test_fake_orchestrator_matches_contract(client, adult):
    events = await _ask(client, adult, await _conversation(client, adult))

    names = [name for name, _ in events]
    assert names[0] == "message_start"
    assert names[-2:] == ["sources", "message_end"]
    assert {"tool_status", "text_delta", "card"} <= set(names)


async def test_tokens_count_against_budget_even_when_answer_fails(
    with_deps, make_client, redis, adult
):
    billed_then_failed = scripted(
        {"type": "sources", "sources": []},
        {"type": "usage", "model": "m", "tokens_in": 500, "tokens_out": 50, "tool_calls": []},
        {"type": "error", "error": {"code": "internal", "message": "x"}},
    )
    async with make_client(with_deps(answer=billed_then_failed)) as http:
        await _ask(http, adult, await _conversation(http, adult))

    assert await redis.get("tokens:2026-10-10") == "550"


async def test_missing_sources_event_is_added_before_end(with_deps, make_client, adult):
    no_sources = scripted(
        {"type": "text_delta", "text": "ok"},
        {"type": "usage", "model": "m", "tokens_in": 1, "tokens_out": 1, "tool_calls": []},
    )
    async with make_client(with_deps(answer=no_sources)) as http:
        events = await _ask(http, adult, await _conversation(http, adult))

    assert events[-2] == ("sources", {"type": "sources", "sources": []})


async def test_parallel_questions_never_exceed_daily_limit(with_deps, make_client, settings, adult):
    import asyncio

    roomy = settings.model_copy(update={"per_ip_requests_per_minute": 100})
    async with make_client(with_deps(settings=roomy)) as http:
        conversation_id = await _conversation(http, adult)
        responses = await asyncio.gather(
            *(
                http.post(
                    f"/conversations/{conversation_id}/messages",
                    headers=adult.headers,
                    json={"content": f"q{i}"},
                )
                for i in range(20)
            )
        )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200] * 15 + [429] * 5
