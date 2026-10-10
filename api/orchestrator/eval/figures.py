"""Every number in an answer, matched to the tool results it could have come from.

A figure is `exact` when a tool result (or the user's own question) holds that value at the
precision shown, `derived` when simple arithmetic on tool values could give it (a goal
difference, a per-game average, a price's implied probability) and `unexplained` otherwise.
`derived` is weak evidence: with enough values, arithmetic explains most small numbers, so
derived figures are listed for review rather than trusted. Dates and times are pulled out separately and compared, in UK
time, with the timestamps in the tool results.
"""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations
from typing import Any

from orchestrator.eval.checks import MONTH_PATTERN, UK, month_number

CONTEXT_CHARS = 40
MAX_DERIVATION_VALUES = 400  # pairwise arithmetic is skipped beyond this many distinct values
MAX_MATCHES_IN_A_SEASON = 38  # per-game averages divide by a number of matches
EPSILON = 1e-9
QUESTION_SOURCE = "question"
CONSTANT_SOURCE = "constant"

# Internal ids and match scores are never shown to users, so they ground nothing.
UNGROUNDED_KEYS = frozenset({"id", "fixture_id", "team_id", "player_id", "score"})
UNGROUNDED_INPUTS = frozenset({"fixture_id", "team_id", "player_id", "opponent_team_id"})
UNGROUNDED_INPUTS_BY_PREFIX = ("team_a_id", "team_b_id")
LOOKUP_TOOLS = frozenset({"resolve_entity"})

# Trivial counts, "per 90", percentages, and the limits the system prompt itself states.
CONSTANTS = (0, 1, 2, 2.5, 6, 8, 10, 18, 24, 48, 90, 100)  # 2.5: the goals line

_PHONE = re.compile(r"\b0808[\s-]?8020[\s-]?133\b|\b24/7\b")  # the helpline and its hours
_SEASON = re.compile(r"\b20\d{2}/\d{2}\b")
_ISO_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_DAY_FIRST = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH_PATTERN}\.?(?:,?\s+20\d{{2}})?\b",
    re.IGNORECASE,
)
_DATE_MONTH_FIRST = re.compile(
    rf"\b{MONTH_PATTERN}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\d)(?:,?\s+20\d{{2}})?", re.IGNORECASE
)
_TIME_24H = re.compile(r"\b(\d{1,2}):(\d{2})\b(?:\s?([ap])\.?m\.?)?", re.IGNORECASE)
_TIME_12H = re.compile(r"\b(\d{1,2})(?:[.:](\d{2}))?\s?([ap])\.?m\b\.?", re.IGNORECASE)
# A number not glued to a word on either side; ordinals and a few unit suffixes are allowed.
_NUMBER = re.compile(
    r"(?<![\w.,])(\d+(?:,\d{3})*(?:\.\d+)?)(%|(?:st|nd|rd|th|x|h|hrs?|pts?|pp)\b)?(?![A-Za-z\d])"
)
_DURATION_SUFFIX = re.compile(r"h|hrs?", re.IGNORECASE)
_DURATION_UNIT = re.compile(r"\s?-?(?:minutes?|mins?|hours?|hrs?|days?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Figure:
    raw: str
    value: float
    decimals: int
    context: str
    is_duration: bool = False  # "3 hours", "2 days": may be the age of the data


@dataclass(frozen=True)
class Moment:
    raw: str
    kind: str  # 'date' -> (day, month); 'time' -> (hour, minute)
    value: tuple[int, int]
    context: str


@dataclass(frozen=True)
class Verdict:
    kind: str  # 'exact' | 'derived' | 'unexplained'
    sources: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Evidence:
    """Values an answer may quote, each with the sources it appears in. `loose` values
    (probabilities as percentages) may be rounded to a whole number; `durations` (the age
    of the data, days until kick-off) only match a figure followed by a unit of time."""

    values: Mapping[float, frozenset[str]] = field(default_factory=dict)
    loose: Mapping[float, frozenset[str]] = field(default_factory=dict)
    durations: Mapping[float, frozenset[str]] = field(default_factory=dict)
    times: frozenset[tuple[int, int]] = frozenset()
    dates: frozenset[tuple[int, int]] = frozenset()


def _context(text: str, start: int, end: int) -> str:
    snippet = text[max(0, start - CONTEXT_CHARS) : end + CONTEXT_CHARS]
    return " ".join(snippet.split())


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    """Replace matches with spaces, keeping every other character's position."""
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _hour_24(hour: int, meridiem: str | None) -> int:
    if meridiem is None:
        return hour
    return hour % 12 + (12 if meridiem.lower() == "p" else 0)


def _dates(text: str) -> list[tuple[int, Moment]]:
    day_first = [
        (m, int(m.group(1)), month_number(m.group(2))) for m in _DATE_DAY_FIRST.finditer(text)
    ]
    month_first = [
        (m, int(m.group(2)), month_number(m.group(1)))
        for m in _DATE_MONTH_FIRST.finditer(_blank(text, _DATE_DAY_FIRST))
    ]
    return [
        (m.start(), Moment(m.group(0), "date", (day, month), _context(text, m.start(), m.end())))
        for m, day, month in [*day_first, *month_first]
    ]


def _times(text: str) -> list[tuple[int, Moment]]:
    clock = [
        (m, _hour_24(int(m.group(1)), m.group(3)), int(m.group(2)))
        for m in _TIME_24H.finditer(text)
    ]
    twelve = [
        (m, _hour_24(int(m.group(1)), m.group(3)), int(m.group(2) or 0))
        for m in _TIME_12H.finditer(_blank(text, _TIME_24H))
    ]
    return [
        (m.start(), Moment(m.group(0), "time", (hour, minute), _context(text, m.start(), m.end())))
        for m, hour, minute in [*clock, *twelve]
    ]


def _in_order(found: list[tuple[int, Moment]]) -> list[Moment]:
    return [moment for _, moment in sorted(found, key=lambda pair: pair[0])]


def _is_duration(match: re.Match[str], text: str) -> bool:
    suffix = match.group(2) or ""
    return bool(_DURATION_SUFFIX.fullmatch(suffix) or _DURATION_UNIT.match(text, match.end()))


def extract(text: str) -> tuple[list[Figure], list[Moment]]:
    """(figures, moments) in an answer. Moments are dates then times, each in text order."""
    cleaned = _blank(_blank(text, _PHONE), _SEASON)
    moments = [*_in_order(_dates(cleaned)), *_in_order(_times(cleaned))]
    for pattern in (_DATE_DAY_FIRST, _DATE_MONTH_FIRST, _TIME_24H, _TIME_12H):
        cleaned = _blank(cleaned, pattern)
    figures = [
        Figure(
            raw=m.group(0),
            value=float(m.group(1).replace(",", "")),
            decimals=len(m.group(1).partition(".")[2]),
            context=_context(text, m.start(), m.end()),
            is_duration=_is_duration(m, cleaned),
        )
        for m in _NUMBER.finditer(cleaned)
    ]
    return figures, moments


def _numbers_in(text: str) -> list[float]:
    return [f.value for f in extract(text)[0]]


@dataclass
class _Collector:
    """Mutable while one answer's evidence is gathered; frozen into Evidence at the end."""

    now: datetime
    values: dict[float, set[str]] = field(default_factory=dict)
    loose: dict[float, set[str]] = field(default_factory=dict)
    durations: dict[float, set[str]] = field(default_factory=dict)
    times: set[tuple[int, int]] = field(default_factory=set)
    dates: set[tuple[int, int]] = field(default_factory=set)

    def add(self, value: float, source: str, *, loose: bool = False) -> None:
        (self.loose if loose else self.values).setdefault(float(value), set()).add(source)

    def add_duration(self, value: float, source: str) -> None:
        self.durations.setdefault(float(abs(value)), set()).add(source)

    def add_moment(self, moment: datetime, source: str) -> None:
        local = moment.astimezone(UK)
        rounded = local + timedelta(seconds=30)  # an answer may round the seconds up
        self.dates.add((local.day, local.month))
        self.times.update({(local.hour, local.minute), (rounded.hour, rounded.minute)})
        self.add_duration((local.date() - self.now.astimezone(UK).date()).days, source)

    def add_age(self, moment: datetime, source: str) -> None:
        """How old data is, as an answer might put it: whole minutes, hours or days."""
        seconds = (self.now - moment).total_seconds()
        for unit in (60, 3600, 86400):
            self.add_duration(math.floor(seconds / unit), source)
            self.add_duration(round(seconds / unit), source)

    def add_number(self, key: str, value: float, source: str) -> None:
        self.add(value, source)
        if isinstance(value, float) and not value.is_integer() and abs(value) < 2:
            self.add(value * 100, source, loose=True)  # a probability shown as a percentage
            if key == "overround":
                self.add((value - 1) * 100, source, loose=True)

    def add_text(self, value: str, source: str) -> None:
        if _ISO_STAMP.match(value):
            self.add_moment(datetime.fromisoformat(value), source)
        elif _ISO_DATE.match(value):
            __, month, day = (int(part) for part in value.split("-"))
            self.dates.add((day, month))
        else:
            for number in _numbers_in(value):
                self.add(number, source)

    def walk(self, key: str, node: Any, source: str) -> None:
        if key in UNGROUNDED_KEYS or node is None or isinstance(node, bool):
            return
        if isinstance(node, Mapping):
            for child_key, child in node.items():
                self.walk(child_key, child, source)
        elif isinstance(node, list):
            self.add(len(node), source)
            for child in node:
                self.walk(key, child, source)
        elif isinstance(node, (int, float)):
            self.add_number(key, node, source)
        elif isinstance(node, str):
            self.add_text(node, source)


def _is_grounding_input(key: str) -> bool:
    return key not in UNGROUNDED_INPUTS and key not in UNGROUNDED_INPUTS_BY_PREFIX


def _collect_call(collector: _Collector, call: Mapping[str, Any]) -> None:
    result = call["result"]
    if not result.get("ok"):
        collector.add_text(result["error"]["message"], CONSTANT_SOURCE)
        return
    if call["name"] in LOOKUP_TOOLS:
        return
    source = result["source"]
    for key, value in call["input"].items():
        if _is_grounding_input(key):
            collector.walk(key, value, source)
    collector.walk("", {k: result[k] for k in ("warnings", "data")}, source)
    as_of = datetime.fromisoformat(result["as_of"])
    collector.add_moment(as_of, source)
    collector.add_age(as_of, source)
    if result.get("freshness_limit_hours") is not None:
        collector.add(result["freshness_limit_hours"], source)


def evidence_from(calls: Iterable[Mapping[str, Any]], *, question: str, now: datetime) -> Evidence:
    """Everything an answer may quote: tool results, the user's own numbers and constants.

    `calls` are {name, input, result}; `question` is the question plus any chat history.
    """
    collector = _Collector(now=now)
    for call in calls:
        _collect_call(collector, call)
    for number in _numbers_in(question):
        collector.add(number, QUESTION_SOURCE)
    for constant in CONSTANTS:
        collector.add(constant, CONSTANT_SOURCE)
    collector.add_moment(now, CONSTANT_SOURCE)
    return Evidence(
        values={v: frozenset(s) for v, s in collector.values.items()},
        loose={v: frozenset(s) for v, s in collector.loose.items()},
        durations={v: frozenset(s) for v, s in collector.durations.items()},
        times=frozenset(collector.times),
        dates=frozenset(collector.dates),
    )


def _tolerance(decimals: int) -> float:
    return 0.5 * 10**-decimals + EPSILON


def _matches(figure: Figure, value: float, *, loose: bool) -> bool:
    """Does `value`, rounded to the figure's precision, give the figure? A whole-number
    figure only matches a whole value, unless the value is one that is normally rounded."""
    if figure.decimals == 0 and not loose and not float(value).is_integer():
        return False
    return abs(abs(value) - figure.value) <= _tolerance(figure.decimals)


def _exact_sources(figure: Figure, evidence: Evidence) -> frozenset[str]:
    strict = [s for v, s in evidence.values.items() if _matches(figure, v, loose=False)]
    loose = [s for v, s in evidence.loose.items() if _matches(figure, v, loose=True)]
    durations = [
        s
        for v, s in evidence.durations.items()
        if figure.is_duration and _matches(figure, v, loose=True)
    ]
    return frozenset().union(*strict, *loose, *durations)


def _is_tool_value(sources: frozenset[str]) -> bool:
    return bool(sources - {QUESTION_SOURCE, CONSTANT_SOURCE})


def _derivations(evidence: Evidence) -> Iterable[float]:
    """Arithmetic an answer might reasonably do on tool values: sums and differences,
    per-match averages, shares, a price's implied probability, and gaps between percentages."""
    data = sorted(v for v, s in evidence.values.items() if _is_tool_value(s))
    percentages = sorted(evidence.loose)
    if len(data) + len(percentages) > MAX_DERIVATION_VALUES:
        return
    counts = [v for v in data if v.is_integer() and v > 0]
    for a, b in combinations(data, 2):
        yield a + b
        yield a - b
    for total in data:
        for matches in counts:
            if 2 <= matches <= MAX_MATCHES_IN_A_SEASON:
                yield total / matches
    for part, whole in combinations(counts, 2):  # sorted, so part <= whole
        if whole <= MAX_MATCHES_IN_A_SEASON:
            yield part / whole * 100
    for price in data:
        if price > 1 and not price.is_integer():
            yield 100 / price
    for pct in (*percentages, *(v for v in data if 0 < v < 100)):
        yield 100 - pct
    for pct in percentages:
        if pct > 0:
            yield 100 / pct  # the fair price for a model probability
    for a, b in combinations(percentages, 2):
        yield a - b


def classify(figure: Figure, evidence: Evidence) -> Verdict:
    sources = _exact_sources(figure, evidence)
    if sources:
        return Verdict("exact", sources)
    if any(_matches(figure, d, loose=True) for d in _derivations(evidence)):
        return Verdict("derived")
    return Verdict("unexplained")
