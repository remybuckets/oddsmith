import pytest

from orchestrator import tools
from orchestrator.tests.seed import NOW
from orchestrator.tools import is_offered, run_tool, tool_definitions
from orchestrator.tools.context import ToolContext
from orchestrator.tools.contract import tool_specs

NO_DB = ToolContext(conn=None, now=NOW)  # for paths that fail before any query


def test_contract_lists_eleven_tools():
    assert len(tool_specs()) == 11


def test_registry_only_implements_contract_tools():
    assert set(tools.RUNNERS) <= set(tool_specs())


def test_search_news_is_offered_only_when_news_enabled():
    assert is_offered("search_news", news_enabled=False) is False
    assert is_offered("search_news", news_enabled=True) is True
    assert is_offered("get_team_stats", news_enabled=False) is True


def test_tool_definitions_send_only_name_description_and_input_schema():
    definitions = tool_definitions(news_enabled=False)

    assert definitions
    for definition in definitions:
        assert set(definition) == {"name", "description", "input_schema"}


def test_tool_definitions_exclude_news_when_disabled():
    names = {d["name"] for d in tool_definitions(news_enabled=False)}
    assert "search_news" not in names
    assert names == set(tools.RUNNERS) - {"search_news"}


@pytest.mark.asyncio
async def test_unknown_tool_is_unsupported():
    result = await run_tool(NO_DB, "drop_tables", {})
    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported"


@pytest.mark.asyncio
async def test_contract_tool_without_runner_is_unsupported(monkeypatch):
    monkeypatch.delitem(tools.RUNNERS, "get_team_stats")
    result = await run_tool(NO_DB, "get_team_stats", {"team_id": 1})
    assert result["error"]["code"] == "unsupported"


@pytest.mark.asyncio
async def test_invalid_input_names_the_field():
    result = await run_tool(NO_DB, "get_team_stats", {"team_id": "arsenal"})

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert "team_id" in result["error"]["message"]


@pytest.mark.asyncio
async def test_unknown_field_is_invalid_input():
    result = await run_tool(NO_DB, "get_team_stats", {"team_id": 1, "sql": "x"})
    assert result["error"]["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_min_properties_is_enforced():
    result = await run_tool(NO_DB, "get_fixtures", {})
    assert result["error"]["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_bad_date_format_is_invalid_input():
    result = await run_tool(NO_DB, "get_fixtures", {"date_from": "next saturday"})
    assert result["error"]["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_schema_defaults_are_applied_before_running(monkeypatch):
    seen = {}

    async def fake(ctx, args):
        seen.update(args)
        return {"ok": False, "error": {"code": "no_data", "message": "none"}}

    monkeypatch.setitem(tools.RUNNERS, "get_team_stats", fake)
    await run_tool(NO_DB, "get_team_stats", {"team_id": 1})

    assert seen == {"team_id": 1, "season": "2026/27", "venue": "all"}


@pytest.mark.asyncio
async def test_unexpected_exception_returns_safe_internal_error(monkeypatch, caplog):
    async def boom(ctx, args):
        raise RuntimeError("SELECT * FROM secrets")

    monkeypatch.setitem(tools.RUNNERS, "get_team_stats", boom)
    result = await run_tool(NO_DB, "get_team_stats", {"team_id": 1})

    assert result["error"]["code"] == "internal"
    assert "SELECT" not in result["error"]["message"]
    assert "SELECT * FROM secrets" in caplog.text


@pytest.mark.asyncio
async def test_output_not_matching_contract_is_internal_error(monkeypatch, caplog):
    async def bad_shape(ctx, args):
        return {
            "ok": True,
            "source": "s",
            "as_of": "2026-10-07T12:00:00Z",
            "is_stale": False,
            "freshness_limit_hours": 48,
            "warnings": [],
            "data": {"team": "Arsenal"},
        }

    monkeypatch.setitem(tools.RUNNERS, "get_team_stats", bad_shape)
    result = await run_tool(NO_DB, "get_team_stats", {"team_id": 1})

    assert result["error"]["code"] == "internal"
    assert "get_team_stats" in caplog.text
