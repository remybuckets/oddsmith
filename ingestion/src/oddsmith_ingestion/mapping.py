"""The one place where provider values become schema values (enums, names, seasons)."""

import re
import unicodedata

# Letters NFKD does not decompose into base letter + accent.
_SPECIAL_LETTERS = str.maketrans(
    {"ø": "o", "ł": "l", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i", "þ": "th"}
)


def alias_search(text: str) -> str:
    """Lowercased, accent-stripped, whitespace-collapsed form for entity_aliases.alias_search."""
    lowered = text.strip().lower().translate(_SPECIAL_LETTERS)
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped)


_POSITIONS = {
    "goalkeeper": "GK",
    "g": "GK",
    "defender": "DEF",
    "d": "DEF",
    "midfielder": "MID",
    "m": "MID",
    "attacker": "FWD",
    "f": "FWD",
}


def position(raw: str | None) -> str | None:
    """API-Football position ('Goalkeeper' in squads, 'G' in match stats) -> players.position."""
    return _POSITIONS.get(raw.strip().lower()) if raw else None


_FIXTURE_STATUSES = {
    **dict.fromkeys(["TBD", "NS"], "scheduled"),
    **dict.fromkeys(["1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"], "live"),
    **dict.fromkeys(["FT", "AET", "PEN", "AWD", "WO"], "finished"),
    "PST": "postponed",
    **dict.fromkeys(["CANC", "ABD"], "cancelled"),
}


def fixture_status(short: str) -> str:
    """API-Football fixture.status.short -> fixtures.status. Unknown codes fail loudly."""
    try:
        return _FIXTURE_STATUSES[short]
    except KeyError:
        raise ValueError(f"unknown API-Football fixture status {short!r}") from None


_SUSPENSION_WORDS = ("card", "suspen", "ban")
_NOT_AN_ABSENCE = ("loan agreement",)


def availability_status(kind: str, reason: str | None) -> str | None:
    """API-Football injury (type, reason) -> availability.status, or None to skip the row.

    'Loan agreement' means ineligible against the parent club, which none of
    injured/suspended/doubtful describes, so it is skipped.
    """
    reason_lower = (reason or "").lower()
    if any(word in reason_lower for word in _NOT_AN_ABSENCE):
        return None
    if kind == "Questionable":
        return "doubtful"
    if kind != "Missing Fixture":
        return None
    if any(word in reason_lower for word in _SUSPENSION_WORDS):
        return "suspended"
    return "injured"


_ROUND = re.compile(r"^Regular Season - (\d+)$")


def matchweek(round_name: str | None) -> int | None:
    """'Regular Season - 7' -> 7."""
    match = _ROUND.match(round_name or "")
    return int(match.group(1)) if match else None


def season_label(season: int) -> str:
    """API-Football season year 2024 -> fixtures.season '2024/25'."""
    return f"{season}/{(season + 1) % 100:02d}"


_FIXED_SELECTIONS = {
    "totals": {"Over": "over", "Under": "under"},
    "btts": {"Yes": "yes", "No": "no"},
}


def odds_selection(market: str, name: str, *, home: str, away: str) -> str:
    """The Odds API outcome name -> odds_snapshots.selection."""
    if market == "h2h":
        by_name = {home: "home", away: "away", "Draw": "draw"}
    elif market in _FIXED_SELECTIONS:
        by_name = _FIXED_SELECTIONS[market]
    else:
        raise ValueError(f"unsupported market {market!r}")
    try:
        return by_name[name]
    except KeyError:
        raise ValueError(f"unknown {market} outcome {name!r} for {home} v {away}") from None


_INITIAL = re.compile(r"^(?:[^\W\d_]\.\s*)+")  # any letter, incl. "Ø."
_PARTICLES = {"van", "von", "de", "da", "di", "dos", "das", "del", "le", "la", "ter", "ten"}


def player_name_aliases(name: str) -> set[str]:
    """Aliases derived from a provider name: as given, without initials, surname, and the
    first name of a full two-part name ('Gabriel Magalhães' -> 'Gabriel', the case
    resolve_entity must ask about)."""
    full = name.strip()
    bare = _INITIAL.sub("", full).strip()
    tokens = bare.split()
    aliases = {full, bare}
    if len(tokens) > 1:
        aliases.add(_surname(tokens))
        if bare == full:
            aliases.add(tokens[0])
    return aliases


def _surname(tokens: list[str]) -> str:
    start = len(tokens) - 1
    while start > 0 and tokens[start - 1].lower() in _PARTICLES:
        start -= 1
    return " ".join(tokens[start:])
