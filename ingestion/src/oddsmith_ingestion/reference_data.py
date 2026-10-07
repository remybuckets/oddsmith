"""Hand-curated names that providers don't give us: display short names and nicknames.

Keyed by API-Football team id, but an entry only applies when API-Football's team name
also matches, so a wrong id here can never attach nicknames to the wrong club.
Aliases include The Odds API's team names so odds can be matched to fixtures.
"""

from dataclasses import dataclass

from oddsmith_ingestion.mapping import alias_search


@dataclass(frozen=True)
class TeamRef:
    api_name: str
    short_name: str
    aliases: tuple[str, ...]


_TEAMS: dict[int, TeamRef] = {
    42: TeamRef("Arsenal", "Arsenal", ("Gunners", "The Arsenal", "AFC")),
    66: TeamRef("Aston Villa", "Villa", ("Villa", "AVFC", "Villans")),
    35: TeamRef("Bournemouth", "Bournemouth", ("AFC Bournemouth", "Cherries")),
    55: TeamRef("Brentford", "Brentford", ("Bees",)),
    51: TeamRef(
        "Brighton",
        "Brighton",
        ("Brighton and Hove Albion", "Brighton & Hove Albion", "Seagulls", "BHAFC"),
    ),
    44: TeamRef("Burnley", "Burnley", ("Clarets",)),
    49: TeamRef("Chelsea", "Chelsea", ("Blues", "CFC")),
    1346: TeamRef("Coventry", "Coventry", ("Coventry City", "Sky Blues")),
    52: TeamRef("Crystal Palace", "Palace", ("Palace", "Eagles", "CPFC")),
    45: TeamRef("Everton", "Everton", ("Toffees", "Blues", "EFC")),
    36: TeamRef("Fulham", "Fulham", ("Cottagers", "FFC")),
    64: TeamRef("Hull City", "Hull", ("Hull", "Tigers")),
    57: TeamRef("Ipswich", "Ipswich", ("Ipswich Town", "Tractor Boys", "ITFC")),
    63: TeamRef("Leeds", "Leeds", ("Leeds United", "Leeds Utd", "LUFC")),
    46: TeamRef("Leicester", "Leicester", ("Leicester City", "Foxes", "LCFC")),
    40: TeamRef("Liverpool", "Liverpool", ("Reds", "LFC", "Pool")),
    50: TeamRef("Manchester City", "Man City", ("Man City", "City", "MCFC", "Citizens")),
    33: TeamRef(
        "Manchester United",
        "Man Utd",
        ("Man Utd", "Man United", "Man U", "United", "MUFC", "Red Devils"),
    ),
    34: TeamRef(
        "Newcastle", "Newcastle", ("Newcastle United", "Newcastle Utd", "Magpies", "Toon", "NUFC")
    ),
    65: TeamRef("Nottingham Forest", "Nott'm Forest", ("Forest", "Nottm Forest", "NFFC")),
    62: TeamRef("Sheffield Utd", "Sheff Utd", ("Sheffield United", "Blades")),
    41: TeamRef("Southampton", "Southampton", ("Saints", "SFC")),
    746: TeamRef("Sunderland", "Sunderland", ("Black Cats", "SAFC")),
    47: TeamRef("Tottenham", "Spurs", ("Spurs", "Tottenham Hotspur", "THFC")),
    48: TeamRef("West Ham", "West Ham", ("West Ham United", "Hammers", "Irons", "WHUFC")),
    39: TeamRef("Wolves", "Wolves", ("Wolverhampton", "Wolverhampton Wanderers", "WWFC")),
}

# Player nicknames, keyed by (API-Football team id, a name alias the player already has).
# Applied only if that team's squad has a player with that alias, so a stale entry is inert.
PLAYER_NICKNAMES: dict[tuple[int, str], tuple[str, ...]] = {
    (50, "de bruyne"): ("KDB",),
    (50, "haaland"): ("Erling Haaland",),
    (40, "van dijk"): ("VVD", "Virgil"),
    (40, "salah"): ("Mo Salah", "Mohamed Salah"),
    (42, "odegaard"): ("Martin Odegaard",),
    (42, "saka"): ("Bukayo Saka",),
    (42, "rice"): ("Declan Rice",),
    (33, "fernandes"): ("Bruno", "Bruno Fernandes"),
    (66, "watkins"): ("Ollie Watkins",),
    (49, "palmer"): ("Cole Palmer",),
}


def team_reference(provider_id: int, provider_name: str) -> TeamRef | None:
    ref = _TEAMS.get(provider_id)
    if ref is None or alias_search(ref.api_name) != alias_search(provider_name):
        return None
    return ref
