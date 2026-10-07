from oddsmith_ingestion.reference_data import team_reference


def test_team_reference_applies_when_provider_name_matches():
    ref = team_reference(47, "Tottenham")
    assert ref is not None
    assert ref.short_name == "Spurs"
    assert "Spurs" in ref.aliases
    assert "Tottenham Hotspur" in ref.aliases  # The Odds API's name


def test_team_reference_ignored_when_name_does_not_match():
    # Guards against a wrong provider id attaching nicknames to the wrong club.
    assert team_reference(47, "Chelsea") is None


def test_team_reference_unknown_id():
    assert team_reference(999999, "Somewhere FC") is None
