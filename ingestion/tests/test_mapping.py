import pytest

from oddsmith_ingestion import mapping


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ødegaard", "odegaard"),
        ("  Gyökeres ", "gyokeres"),
        ("Martín Zubimendi", "martin zubimendi"),
        ("Łukasz Fabiański", "lukasz fabianski"),
        ("Alexander-Arnold", "alexander-arnold"),
        ("Man  Utd", "man utd"),
        ("Søren Æbelø", "soren aebelo"),
    ],
)
def test_alias_search_lowercases_and_strips_accents(raw, expected):
    assert mapping.alias_search(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Goalkeeper", "GK"),
        ("G", "GK"),
        ("Defender", "DEF"),
        ("D", "DEF"),
        ("Midfielder", "MID"),
        ("M", "MID"),
        ("Attacker", "FWD"),
        ("F", "FWD"),
        (None, None),
        ("Coach", None),
    ],
)
def test_position(raw, expected):
    assert mapping.position(raw) == expected


@pytest.mark.parametrize(
    ("short", "expected"),
    [
        ("TBD", "scheduled"),
        ("NS", "scheduled"),
        ("1H", "live"),
        ("HT", "live"),
        ("2H", "live"),
        ("ET", "live"),
        ("BT", "live"),
        ("P", "live"),
        ("SUSP", "live"),
        ("INT", "live"),
        ("LIVE", "live"),
        ("FT", "finished"),
        ("AET", "finished"),
        ("PEN", "finished"),
        ("AWD", "finished"),
        ("WO", "finished"),
        ("PST", "postponed"),
        ("CANC", "cancelled"),
        ("ABD", "cancelled"),
    ],
)
def test_fixture_status(short, expected):
    assert mapping.fixture_status(short) == expected


def test_unknown_fixture_status_raises():
    with pytest.raises(ValueError, match="XYZ"):
        mapping.fixture_status("XYZ")


@pytest.mark.parametrize(
    ("kind", "reason", "expected"),
    [
        ("Missing Fixture", "Knee Injury", "injured"),
        ("Missing Fixture", "Illness", "injured"),
        ("Missing Fixture", "Red Card", "suspended"),
        ("Missing Fixture", "Yellow Cards", "suspended"),
        ("Missing Fixture", "Suspended", "suspended"),
        ("Questionable", "Muscle Injury", "doubtful"),
        ("Missing Fixture", "Loan agreement", None),  # ineligible vs parent club, not injured
        ("Something New", "Knee Injury", None),
    ],
)
def test_availability_status(kind, reason, expected):
    assert mapping.availability_status(kind, reason) == expected


@pytest.mark.parametrize(
    ("round_name", "expected"),
    [("Regular Season - 1", 1), ("Regular Season - 38", 38), ("Play-offs", None), (None, None)],
)
def test_matchweek(round_name, expected):
    assert mapping.matchweek(round_name) == expected


def test_season_label():
    assert mapping.season_label(2024) == "2024/25"
    assert mapping.season_label(2099) == "2099/00"


@pytest.mark.parametrize(
    ("market", "name", "expected"),
    [
        ("h2h", "Arsenal", "home"),
        ("h2h", "Leeds United", "away"),
        ("h2h", "Draw", "draw"),
        ("totals", "Over", "over"),
        ("totals", "Under", "under"),
        ("btts", "Yes", "yes"),
        ("btts", "No", "no"),
    ],
)
def test_odds_selection(market, name, expected):
    assert mapping.odds_selection(market, name, home="Arsenal", away="Leeds United") == expected


def test_odds_selection_unknown_raises():
    with pytest.raises(ValueError):
        mapping.odds_selection("h2h", "Chelsea", home="Arsenal", away="Leeds United")
    with pytest.raises(ValueError):
        mapping.odds_selection("player_goal_scorer", "Yes", home="A", away="B")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("B. Saka", {"B. Saka", "Saka"}),
        ("M. Ødegaard", {"M. Ødegaard", "Ødegaard"}),
        ("Gabriel Magalhães", {"Gabriel Magalhães", "Magalhães", "Gabriel"}),
        ("V. van Dijk", {"V. van Dijk", "van Dijk"}),
        ("Kepa", {"Kepa"}),
        ("Ø. Hermansen", {"Ø. Hermansen", "Hermansen"}),
        ("M. Lewis-Skelly", {"M. Lewis-Skelly", "Lewis-Skelly"}),
    ],
)
def test_player_name_aliases(name, expected):
    assert mapping.player_name_aliases(name) == expected
