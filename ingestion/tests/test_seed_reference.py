import copy

from conftest import load_fixture

from oddsmith_ingestion.jobs.seed_reference import seed_reference

ARSENAL = 42


class FakeApiFootball:
    """Replays recorded responses. Only Arsenal has a recorded squad; others are empty."""

    def __init__(self, squad_override=None):
        self.calls: list[tuple] = []
        self._squad = squad_override or load_fixture("api_football", "squad")["response"]

    async def teams(self, season):
        self.calls.append(("teams", season))
        return load_fixture("api_football", "teams")["response"]

    async def squad(self, team_id):
        self.calls.append(("squad", team_id))
        return self._squad if team_id == ARSENAL else []

    async def get_all(self, path, params):
        self.calls.append((path, params["team"]))
        if params["team"] != ARSENAL:
            return []
        return load_fixture("api_football", "players_team_page1")["response"]


async def alias_targets(db, alias):
    rows = await db.fetch(
        """SELECT COALESCE(t.name, p.name) AS name FROM entity_aliases a
           LEFT JOIN teams t ON a.entity_type = 'team' AND t.id = a.entity_id
           LEFT JOIN players p ON a.entity_type = 'player' AND p.id = a.entity_id
           WHERE a.alias_search = $1 ORDER BY 1""",
        alias,
    )
    return [r["name"] for r in rows]


async def test_seeds_all_teams_with_short_names_and_nicknames(db):
    # Act
    await seed_reference(db, FakeApiFootball(), season=2024)
    # Assert
    assert await db.fetchval("SELECT count(*) FROM teams") == 20
    spurs = await db.fetchrow("SELECT * FROM teams WHERE provider_id = 47")
    assert spurs["name"] == "Tottenham"
    assert spurs["short_name"] == "Spurs"
    assert "Spurs" in spurs["aliases"]
    assert await alias_targets(db, "spurs") == ["Tottenham"]
    assert await alias_targets(db, "villa") == ["Aston Villa"]
    assert await alias_targets(db, "blues") == ["Chelsea", "Everton"]  # ambiguous on purpose


async def test_seeds_squad_players_with_positions_and_aliases(db):
    await seed_reference(db, FakeApiFootball(), season=2024)

    saka = await db.fetchrow(
        "SELECT p.*, t.provider_id AS team_provider_id FROM players p "
        "JOIN teams t ON t.id = p.team_id WHERE p.name = 'B. Saka'"
    )
    assert saka["team_provider_id"] == ARSENAL
    assert saka["position"] == "FWD"
    assert await alias_targets(db, "saka") == ["B. Saka"]
    assert await alias_targets(db, "odegaard") == ["M. Ødegaard"]
    assert await alias_targets(db, "gunners") == ["Arsenal"]


async def test_full_names_from_players_endpoint_become_aliases(db):
    await seed_reference(db, FakeApiFootball(), season=2024, include_full_names=True)
    # K. Havertz is in both the squad and players page 1 (firstname 'Kai Lukas').
    assert await alias_targets(db, "kai havertz") == ["K. Havertz"]
    assert await alias_targets(db, "kai lukas havertz") == ["K. Havertz"]


async def test_full_names_skipped_when_disabled(db):
    client = FakeApiFootball()
    await seed_reference(db, client, season=2024, include_full_names=False)
    assert await alias_targets(db, "kai havertz") == []
    assert not any(call[0] == "players" for call in client.calls)


async def test_is_idempotent(db):
    await seed_reference(db, FakeApiFootball(), season=2024)
    counts = await db.fetchrow(
        "SELECT (SELECT count(*) FROM teams) t, (SELECT count(*) FROM players) p, "
        "(SELECT count(*) FROM entity_aliases) a"
    )
    await seed_reference(db, FakeApiFootball(), season=2024)
    again = await db.fetchrow(
        "SELECT (SELECT count(*) FROM teams) t, (SELECT count(*) FROM players) p, "
        "(SELECT count(*) FROM entity_aliases) a"
    )
    assert dict(again) == dict(counts)


async def test_player_no_longer_in_any_squad_loses_team(db):
    await seed_reference(db, FakeApiFootball(), season=2024)
    squad = copy.deepcopy(load_fixture("api_football", "squad")["response"])
    squad[0]["players"] = [p for p in squad[0]["players"] if p["name"] != "B. Saka"]

    await seed_reference(db, FakeApiFootball(squad_override=squad), season=2024)

    assert await db.fetchval("SELECT team_id FROM players WHERE name = 'B. Saka'") is None


async def test_returns_rows_written_and_records_job_run(db):
    rows = await seed_reference(db, FakeApiFootball(), season=2024)
    run = await db.fetchrow("SELECT * FROM job_runs WHERE name = 'seed_reference'")
    assert run["status"] == "success"
    assert run["rows"] == rows
    assert rows >= 20 + 31  # teams + Arsenal squad


async def test_tiny_squad_response_does_not_detach_the_rest_of_the_club(db):
    await seed_reference(db, FakeApiFootball(), season=2024)
    squad = copy.deepcopy(load_fixture("api_football", "squad")["response"])
    squad[0]["players"] = squad[0]["players"][:3]  # truncated provider response

    await seed_reference(db, FakeApiFootball(squad_override=squad), season=2024)

    assert await db.fetchval("SELECT team_id FROM players WHERE name = 'B. Saka'") is not None


async def test_removed_aliases_are_pruned(db):
    await seed_reference(db, FakeApiFootball(), season=2024)
    squad = copy.deepcopy(load_fixture("api_football", "squad")["response"])
    saka = next(p for p in squad[0]["players"] if p["name"] == "B. Saka")
    saka["name"] = "Bukayo Saka"  # provider renames the player

    await seed_reference(db, FakeApiFootball(squad_override=squad), season=2024)

    assert await alias_targets(db, "b. saka") == []
    assert await alias_targets(db, "bukayo saka") == ["Bukayo Saka"]


async def test_player_in_two_squads_keeps_existing_club(db):
    # Arrange: Saka is at Arsenal; then a second club's squad also lists him
    await seed_reference(db, FakeApiFootball(), season=2024)
    squad = load_fixture("api_football", "squad")["response"]
    saka = next(p for p in squad[0]["players"] if p["name"] == "B. Saka")

    class TwoSquads(FakeApiFootball):
        async def squad(self, team_id):
            if team_id == 66:  # listed after Arsenal in teams.json
                return [{"team": {"id": 66}, "players": [saka]}]
            return await super().squad(team_id)

    # Act
    await seed_reference(db, TwoSquads(), season=2024)

    # Assert
    club = await db.fetchval(
        "SELECT t.provider_id FROM players p JOIN teams t ON t.id = p.team_id "
        "WHERE p.name = 'B. Saka'"
    )
    assert club == ARSENAL
