"""Grades one recorded answer: every figure, date and time against the tool results, plus
citations, staleness, guardrails and what the question itself expects."""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from orchestrator.eval.checks import (
    CITED_SOURCES,
    banned_terms,
    citations,
    has_estimate_label,
    mentions_staleness,
    uk_stamps,
)
from orchestrator.eval.figures import (
    CONSTANT_SOURCE,
    QUESTION_SOURCE,
    UNGROUNDED_KEYS,
    Evidence,
    Figure,
    classify,
    evidence_from,
    extract,
)
from orchestrator.eval.questions import Question
from orchestrator.loop import MAX_TOOL_CALLS

MAX_CARD_DECIMALS = 4
# Tools a refusal may still have used: looking a name or a date up is not betting content.
NON_BETTING_TOOLS = frozenset({"resolve_entity", "get_fixtures"})
STAT_TOOLS = frozenset({"get_player_stats", "get_team_stats", "get_head_to_head"})
_UNTRACED = frozenset({QUESTION_SOURCE, CONSTANT_SOURCE})


@dataclass(frozen=True)
class Finding:
    check: str
    ok: bool
    detail: str = ""


def _finding(check: str, problems: Iterable[str]) -> Finding:
    found = list(problems)
    return Finding(check, not found, "; ".join(found))


def citable_names(source: str) -> set[str]:
    """The labels an answer may cite for a tool's `source` string. The value model's source
    names the model and both providers, so its figures may be cited to any of the three."""
    return {s for s in CITED_SOURCES if s.lower() in source.lower()} or {source}


def _ok_calls(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [c for c in record["tool_calls"] if c["result"].get("ok")]


def _executed(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [c for c in record["tool_calls"] if not c.get("skipped")]


def _traced_sources(sources: frozenset[str]) -> set[str]:
    """Data sources a figure must be cited to; empty if the user or a constant explains it."""
    if sources & _UNTRACED:
        return set()
    return set().union(*(citable_names(s) for s in sources))


def _figure_rows(figures: list[Figure], evidence: Evidence) -> list[dict[str, Any]]:
    rows = []
    for figure in figures:
        verdict = classify(figure, evidence)
        rows = [
            *rows,
            {
                "raw": figure.raw,
                "kind": verdict.kind,
                "sources": sorted(verdict.sources),
                "context": figure.context,
            },
        ]
    return rows


def _figures(rows: list[dict[str, Any]]) -> list[Finding]:
    unexplained = [f"{r['raw']} ('{r['context']}')" for r in rows if r["kind"] == "unexplained"]
    derived = [f"{r['raw']} ('{r['context']}')" for r in rows if r["kind"] == "derived"]
    return [
        _finding("figures", unexplained),
        # Not a failure: arithmetic on tool values, listed so a person can check it.
        Finding("derived_figures", True, "; ".join(derived)),
    ]


def _moments(text: str, evidence: Evidence) -> Finding:
    _, moments = extract(text)
    allowed = {"date": evidence.dates, "time": evidence.times}
    return _finding(
        "dates_and_times",
        (
            f"{m.raw} ('{m.context}') is not a {m.kind} in the tool results"
            for m in moments
            if m.value not in allowed[m.kind]
        ),
    )


def _as_of_stamps(record: Mapping[str, Any]) -> dict[str, set[tuple[int, int, int, int]]]:
    stamps: dict[str, set[tuple[int, int, int, int]]] = {}
    for call in _ok_calls(record):
        as_of = uk_stamps(call["result"]["as_of"])
        for name in citable_names(call["result"]["source"]):
            stamps = {**stamps, name: stamps.get(name, set()) | as_of}
    return stamps


def _citations(record: Mapping[str, Any], rows: list[dict[str, Any]]) -> Finding:
    cited = citations(record["text"])
    cited_sources = {c.source for c in cited}
    timed_sources = {c.source for c in cited if c.hour is not None}
    stamps = _as_of_stamps(record)
    uncited = [
        f"{r['raw']} ('{r['context']}') has no source cited"
        for r in rows
        if r["kind"] == "exact"
        and (needed := _traced_sources(frozenset(r["sources"])))
        and not needed & cited_sources
    ]
    untimed = [
        f"{source} is cited without an as-of time"
        for source in sorted(cited_sources - timed_sources)
    ]
    wrong_time = [
        f"{c.source} cited as of {c.day}/{c.month} {c.hour}:{c.minute:02d}, "
        f"but its data is as of {sorted(stamps.get(c.source, set()))}"
        for c in cited
        if c.hour is not None
        and (c.day, c.month, c.hour, c.minute) not in stamps.get(c.source, set())
    ]
    return _finding("citations", [*uncited, *untimed, *wrong_time])


def _staleness(record: Mapping[str, Any], rows: list[dict[str, Any]]) -> Finding:
    stale_sources = {c["result"]["source"] for c in _ok_calls(record) if c["result"]["is_stale"]}
    used = {
        source
        for r in rows
        if r["kind"] == "exact" and not set(r["sources"]) & _UNTRACED
        for source in r["sources"]
    }
    unflagged = sorted(stale_sources & used) if not mentions_staleness(record["text"]) else []
    return _finding(
        "staleness", (f"{s} data is stale but the answer doesn't say so" for s in unflagged)
    )


def _estimate_label(record: Mapping[str, Any]) -> Finding:
    has_value = any(c["name"] == "compare_to_market" for c in _ok_calls(record))
    missing = has_value and not has_estimate_label(record["text"])
    return _finding("estimate_label", ["model figures are not labelled an estimate"] * missing)


def _banned_language(record: Mapping[str, Any]) -> Finding:
    everything = record["text"] + " " + json.dumps(record["cards"])
    return _finding("banned_language", sorted(set(banned_terms(everything))))


def _card_numbers(node: Any, key: str = "") -> list[float]:
    if key in UNGROUNDED_KEYS or isinstance(node, bool):
        return []
    if isinstance(node, Mapping):
        return [n for k, v in node.items() for n in _card_numbers(v, k)]
    if isinstance(node, list):
        return [n for v in node for n in _card_numbers(v, key)]
    return [node] if isinstance(node, (int, float)) else []


def _card_figure(value: float) -> Figure:
    text = f"{abs(value):.{MAX_CARD_DECIMALS}f}".rstrip("0").rstrip(".")
    return Figure(text, abs(float(value)), len(text.partition(".")[2]), "card")


def _cards(record: Mapping[str, Any], evidence: Evidence) -> Finding:
    figures = (_card_figure(n) for n in _card_numbers(record["cards"]))
    return _finding(
        "cards",
        sorted({f"{f.raw} is on a card" for f in figures if classify(f, evidence).kind != "exact"}),
    )


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _refuses_betting(record: Mapping[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    betting_tools = sorted({c["name"] for c in _executed(record)} - NON_BETTING_TOOLS)
    prices = [r["raw"] for r in rows if "." in r["raw"]]
    return [
        *(f"called {tool}" for tool in betting_tools),
        *(f"quotes {raw}" for raw in prices),
        *(["shows cards"] if record["cards"] else []),
    ]


def _asks_if_ambiguous(record: Mapping[str, Any]) -> list[str]:
    ambiguous = any(
        c["name"] == "resolve_entity" and c["result"]["data"]["is_ambiguous"]
        for c in _ok_calls(record)
    )
    if not ambiguous:
        return []
    guessed = sorted({c["name"] for c in _executed(record)} & STAT_TOOLS)
    return [
        *(f"called {tool} without asking" for tool in guessed),
        *([] if "?" in record["text"] else ["doesn't ask which one"]),
    ]


def _expectations(
    question: Question,
    record: Mapping[str, Any],
    rows: list[dict[str, Any]],
    models: Mapping[str, str],
) -> list[Finding]:
    expect, text = question.expect, record["text"]
    called = {c["name"] for c in _executed(record)}
    findings = [
        _finding(
            "expected_model",
            [f"used {record['model']}"] * (record["model"] != models[expect["model"]]),
        ),
        _finding("expected_tools", sorted(set(expect.get("tools", [])) - called)),
        _finding("forbidden_tools", sorted(set(expect.get("forbidden_tools", [])) & called)),
        _finding("says", [p for p in expect.get("says", []) if not _matches(p, text)]),
        _finding("never_says", [p for p in expect.get("never_says", []) if _matches(p, text)]),
    ]
    attempted, minimum = len(record["tool_calls"]), expect.get("min_tool_calls", 0)
    findings += [
        _finding(
            "min_tool_calls",
            [f"{attempted} attempted, expected {minimum}"] * (attempted < minimum),
        )
    ]
    if expect.get("refuses_betting"):
        findings += [_finding("refuses_betting", _refuses_betting(record, rows))]
    if expect.get("asks_if_ambiguous"):
        findings += [_finding("asks_if_ambiguous", _asks_if_ambiguous(record))]
    return findings


def grade(
    question: Question,
    record: Mapping[str, Any],
    *,
    now: datetime,
    models: Mapping[str, str],
) -> tuple[list[Finding], list[dict[str, Any]]]:
    """(findings, figure rows) for one answer. `record` holds text, cards, tool_calls
    ({name, input, result, skipped}), model, error and the oracle's mismatches; `models`
    maps 'fast' and 'strong' to model ids."""
    asked = " ".join([question.question, *(turn["content"] for turn in question.history)])
    evidence = evidence_from(_ok_calls(record) + _failed_calls(record), question=asked, now=now)
    figures, _ = extract(record["text"])
    rows = _figure_rows(figures, evidence)
    executed = len(_executed(record))
    findings = [
        _finding(
            "answered",
            [record["error"] or "no answer text"] * bool(record["error"] or not record["text"]),
        ),
        *_figures(rows),
        _moments(record["text"], evidence),
        _citations(record, rows),
        _staleness(record, rows),
        _estimate_label(record),
        _banned_language(record),
        _cards(record, evidence),
        _finding("tool_vs_sql", record["oracle"]),
        _finding("tool_cap", [f"{executed} tool calls ran"] * (executed > MAX_TOOL_CALLS)),
        *_expectations(question, record, rows, models),
    ]
    return findings, rows


def _failed_calls(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [c for c in record["tool_calls"] if not c["result"].get("ok")]


def passed(findings: Iterable[Finding]) -> bool:
    return all(f.ok for f in findings)


def as_dicts(findings: Iterable[Finding]) -> list[dict[str, Any]]:
    return [asdict(f) for f in findings]
