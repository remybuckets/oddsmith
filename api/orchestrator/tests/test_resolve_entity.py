import pytest

from orchestrator.tests.seed import GABRIEL, HAALAND, JESUS, MARTINELLI, ODEGAARD, SAKA, TOT
from orchestrator.tools import run_tool
from orchestrator.tools.resolve_entity import normalise


async def resolve(ctx, **args):
    return await run_tool(ctx, "resolve_entity", args)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ødegaard", "odegaard"),
        ("  Gabriel MAGALHÃES ", "gabriel magalhaes"),
        ("Müller", "muller"),
        ("Søren   Kierkegaard", "soren kierkegaard"),
    ],
)
def test_normalise_lowercases_strips_accents_and_spaces(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.asyncio
async def test_nickname_resolves_to_team(ctx):
    result = await resolve(ctx, query="Spurs")

    assert result["ok"] is True
    top = result["data"]["matches"][0]
    assert (top["entity_type"], top["id"], top["name"]) == ("team", TOT, "Tottenham Hotspur")
    assert top["score"] == 1.0
    assert result["data"]["is_ambiguous"] is False


@pytest.mark.asyncio
async def test_player_match_includes_team_and_position(ctx):
    result = await resolve(ctx, query="saka", entity_type="player")

    top = result["data"]["matches"][0]
    assert top == {
        "entity_type": "player",
        "id": SAKA,
        "name": "Bukayo Saka",
        "team_id": 1,
        "team_name": "Arsenal",
        "position": "FWD",
        "score": 1.0,
    }


@pytest.mark.asyncio
async def test_shared_first_name_is_ambiguous(ctx):
    result = await resolve(ctx, query="Gabriel")

    ids = {m["id"] for m in result["data"]["matches"]}
    assert {GABRIEL, MARTINELLI, JESUS} <= ids
    assert result["data"]["is_ambiguous"] is True


@pytest.mark.asyncio
async def test_accented_query_matches(ctx):
    result = await resolve(ctx, query="Ødegaard")
    assert result["data"]["matches"][0]["id"] == ODEGAARD


@pytest.mark.asyncio
async def test_misspelling_still_matches(ctx):
    result = await resolve(ctx, query="Haalnd")
    assert result["data"]["matches"][0]["id"] == HAALAND


@pytest.mark.asyncio
async def test_each_entity_appears_once(ctx):
    result = await resolve(ctx, query="Villa")

    keys = [(m["entity_type"], m["id"]) for m in result["data"]["matches"]]
    assert len(keys) == len(set(keys))


@pytest.mark.asyncio
async def test_entity_type_filter(ctx):
    result = await resolve(ctx, query="Gabriel", entity_type="team")
    assert result["ok"] is False
    assert result["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_team_filter_restricts_players(ctx):
    result = await resolve(ctx, query="Gabriel", entity_type="player", team_id=TOT)
    assert result["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_no_match_is_not_found_and_echoes_query(ctx):
    result = await resolve(ctx, query="Zzyzx")

    assert result["error"]["code"] == "not_found"
    assert "Zzyzx" in result["error"]["message"]


@pytest.mark.asyncio
async def test_reference_data_has_no_freshness_limit(ctx):
    result = await resolve(ctx, query="Spurs")

    assert result["source"] == "API-Football"
    assert result["freshness_limit_hours"] is None
    assert result["is_stale"] is False
    assert result["as_of"] == "2026-10-06T06:00:00Z"


@pytest.mark.asyncio
async def test_query_too_short_is_invalid(ctx):
    result = await resolve(ctx, query="a")
    assert result["error"]["code"] == "invalid_input"
