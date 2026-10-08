"""Answer cards and the sources line, built from tool results (shapes: contracts/openapi.yaml)."""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

MAX_CARD_PRICES = 4
FORM_STRIP_LENGTH = 10
VALUE_DISCLAIMER = "Estimate, not advice."

_FIXED_LABELS = {
    "draw": "Draw",
    "yes": "Both teams to score",
    "no": "Not both teams to score",
}


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    input: dict[str, Any]
    result: dict[str, Any]


def selection_label(fixture: dict[str, Any], selection: str, line: float | None) -> str:
    if selection in ("home", "away"):
        return fixture[selection]["name"]
    if selection in ("over", "under"):
        return f"{selection.capitalize()} {line:g}"
    return _FIXED_LABELS[selection]


def _source(result: dict[str, Any]) -> dict[str, Any]:
    return {k: result[k] for k in ("source", "as_of", "is_stale")}


def _split_title(name: str, filters: dict[str, Any], opponent: str | None) -> str:
    parts = [
        *([filters["venue"]] if filters["venue"] != "all" else []),
        *([f"last {filters['last_n']}"] if filters.get("last_n") else []),
        *([f"vs {opponent}"] if opponent else []),
    ]
    return f"{name} — {', '.join([*parts, filters['season']])}"


def _rate_text(rate: dict[str, Any]) -> str:
    return f"{rate['count']}/{rate['of']} ({rate['pct']:g}%)"


def _player_card(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result["data"]
    totals, rates = data["totals"], data["per90"]
    opponent = data["matches"][0]["opponent"] if data["filters"].get("opponent_team_id") else None
    stat_rows = [
        ("Goals", "goals"),
        ("Assists", "assists"),
        ("Shots", "shots"),
        ("Shots on target", "shots_on_target"),
        ("xG", "xg"),
        ("xA", "xa"),
        ("Yellow cards", "yellow_cards"),
        ("Red cards", "red_cards"),
    ]
    rows = [
        ["Appearances", data["appearances"], None],
        ["Minutes", data["minutes"], None],
        *([label, totals[key], rates[key]] for label, key in stat_rows if totals[key] is not None),
    ]
    title = _split_title(data["player"]["name"], data["filters"], opponent)
    return [
        {
            "card_type": "stat",
            "title": title,
            "columns": ["Stat", "Total", "Per 90"],
            "rows": rows,
            "form": None,
            "source": _source(result),
        }
    ]


def _team_card(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result["data"]
    optional = [
        ("xG for", data.get("xg_for")),
        ("xG against", data.get("xg_against")),
        ("Corners per match", data.get("corners_per_match")),
    ]
    rows = [
        ["Played", data["played"]],
        ["Won-drawn-lost", f"{data['won']}-{data['drawn']}-{data['lost']}"],
        ["Goals for", data["goals_for"]],
        ["Goals against", data["goals_against"]],
        *([label, value] for label, value in optional if value is not None),
        ["Over 2.5 goals", _rate_text(data["over_2_5"])],
        ["Both teams scored", _rate_text(data["btts"])],
        ["Clean sheets", _rate_text(data["clean_sheets"])],
        ["Cards per match", data["cards_per_match"]],
    ]
    return [
        {
            "card_type": "stat",
            "title": _split_title(data["team"]["name"], data["filters"], None),
            "columns": ["Stat", "Value"],
            "rows": rows,
            "form": data["form"][-FORM_STRIP_LENGTH:],
            "source": _source(result),
        }
    ]


def _odds_card(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result["data"]
    selections = [
        {
            "selection": s["selection"],
            "label": selection_label(data["fixture"], s["selection"], data["line"]),
            "best_price": s["best_price"],
            "best_bookmaker": s["best_bookmaker"],
            "prices": [
                {"bookmaker": p["bookmaker"], "price": p["price"]}
                for p in s["prices"][:MAX_CARD_PRICES]
            ],
        }
        for s in data["selections"]
    ]
    return [
        {
            "card_type": "odds",
            "fixture": data["fixture"],
            "market": data["market"],
            "line": data["line"],
            "selections": selections,
            "source": _source(result),
        }
    ]


def _value_cards(result: dict[str, Any], line: float | None, threshold: float) -> list[dict]:
    data = result["data"]
    return [
        {
            "card_type": "value",
            "fixture": data["fixture"],
            "market": result["market"],
            "line": line,
            "selection": s["selection"],
            "label": selection_label(data["fixture"], s["selection"], line),
            "model_probability": s["model_probability"],
            "implied_probability": s["implied_probability"],
            "edge": s["edge"],
            "best_price": s["best_price"],
            "best_bookmaker": s["best_bookmaker"],
            "is_highlighted": s["edge"] > threshold,
            "disclaimer": VALUE_DISCLAIMER,
            "source": _source(result),
        }
        for s in data["selections"]
    ]


def _cards_for(outcome: ToolOutcome, threshold: float) -> list[dict[str, Any]]:
    if outcome.name == "compare_to_market":
        line = outcome.input.get("line") if outcome.input["market"] == "totals" else None
        return _value_cards({**outcome.result, "market": outcome.input["market"]}, line, threshold)
    builder: Callable[[dict[str, Any]], list[dict]] | None = {
        "get_player_stats": _player_card,
        "get_team_stats": _team_card,
        "get_odds": _odds_card,
    }.get(outcome.name)
    return builder(outcome.result) if builder else []


def _unique_ok(outcomes: Iterable[ToolOutcome]) -> list[ToolOutcome]:
    seen: dict[str, ToolOutcome] = {}
    for outcome in outcomes:
        key = f"{outcome.name}:{json.dumps(outcome.input, sort_keys=True)}"
        if outcome.result.get("ok") and key not in seen:
            seen = {**seen, key: outcome}
    return list(seen.values())


def build_cards(outcomes: Iterable[ToolOutcome], value_threshold: float) -> list[dict[str, Any]]:
    return [card for o in _unique_ok(outcomes) for card in _cards_for(o, value_threshold)]


def collect_sources(outcomes: Iterable[ToolOutcome]) -> list[dict[str, Any]]:
    """Distinct sources of the data the answer used; reference lookups have no freshness."""
    sources = [
        _source(o.result)
        for o in outcomes
        if o.result.get("ok") and o.result.get("freshness_limit_hours") is not None
    ]
    return [s for i, s in enumerate(sources) if s not in sources[:i]]
