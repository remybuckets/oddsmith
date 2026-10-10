"""Text checks on an answer: banned language, estimate and staleness wording, citations."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_PATTERN = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"

# Citation labels, as the system prompt asks for them; the model source is cited by its stem.
CITED_SOURCES = ("API-Football", "The Odds API", "Oddsmith model")

# SPEC.md: never say lock, banker, guaranteed, sure thing or can't lose.
_BANNED = re.compile(
    r"\b(locks?|bankers?|guaranteed|sure[- ]things?|can['’]?t lose)\b", re.IGNORECASE
)
_ESTIMATE = re.compile(r"\bestimates?\b", re.IGNORECASE)
_STALE = re.compile(
    r"stale|out[- ]of[- ]date|older than|\b(?:hours?|hrs?|days?|minutes?|mins?) old\b|\bago\b"
    r"|freshness|last (?:updated|refreshed)|not been (?:updated|refreshed)",
    re.IGNORECASE,
)
_SOURCE = re.compile("|".join(re.escape(s) for s in CITED_SOURCES), re.IGNORECASE)
_DATE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{MONTH_PATTERN}", re.IGNORECASE)
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")
CITATION_REACH = 60  # characters after a source name in which its as-of time is looked for


@dataclass(frozen=True)
class Citation:
    source: str
    day: int | None
    month: int | None
    hour: int | None
    minute: int | None


def banned_terms(text: str) -> list[str]:
    return [m.group(0).lower() for m in _BANNED.finditer(text)]


def has_estimate_label(text: str) -> bool:
    return _ESTIMATE.search(text) is not None


def mentions_staleness(text: str) -> bool:
    return _STALE.search(text) is not None


def month_number(name: str) -> int:
    return MONTHS.index(name[:3].lower()) + 1


def uk_stamp(iso: str) -> tuple[int, int, int, int]:
    """(day, month, hour, minute) in UK time for an ISO 8601 UTC timestamp."""
    moment = datetime.fromisoformat(iso).astimezone(UK)
    return moment.day, moment.month, moment.hour, moment.minute


def uk_stamps(iso: str) -> set[tuple[int, int, int, int]]:
    """uk_stamp with the seconds dropped and with them rounded: an answer may do either."""
    rounded = datetime.fromisoformat(iso) + timedelta(seconds=30)
    return {uk_stamp(iso), uk_stamp(rounded.isoformat())}


def _canonical(source: str) -> str:
    return next(s for s in CITED_SOURCES if s.lower() == source.lower())


def citations(text: str) -> list[Citation]:
    """Each mention of a data source, with the date and time that follow it, if any."""
    mentions = list(_SOURCE.finditer(text))
    found: list[Citation] = []
    for i, mention in enumerate(mentions):
        limit = mentions[i + 1].start() if i + 1 < len(mentions) else len(text)
        tail = text[mention.end() : min(limit, mention.end() + CITATION_REACH)]
        tail = re.split(r"[)\n]", tail, maxsplit=1)[0]
        date, time = _DATE.search(tail), _TIME.search(tail)
        found = [
            *found,
            Citation(
                source=_canonical(mention.group(0)),
                day=int(date.group(1)) if date else None,
                month=month_number(date.group(2)) if date else None,
                hour=int(time.group(1)) if time else None,
                minute=int(time.group(2)) if time else None,
            ),
        ]
    return found
