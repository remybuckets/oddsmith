"""Oracles for the odds tools: prices recomputed from odds_snapshots, and the Poisson
estimate rebuilt from team_match_stats with its own arithmetic."""

import math
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from orchestrator.eval.oracle_common import PROBABILITY_TOLERANCE, Expected

FORM_MATCHES = 10
LEAGUE_WINDOW_DAYS = 365
POISSON_GOALS = 40  # far enough out that the tail is negligible without renormalising
STABLE_CHANGE_PCT = 2.0

# Every snapshot of one market from enabled bookmakers; "latest" is worked out in Python.
_SNAPSHOTS_SQL = """
SELECT s.selection, s.bookmaker, s.price, s.captured_at, b.display_name, b.sort_order
FROM odds_snapshots s
JOIN bookmakers b ON b.key = s.bookmaker
WHERE s.fixture_id = $1
  AND s.market = $2
  AND b.is_enabled
  AND ((s.line IS NULL AND $3::numeric IS NULL) OR s.line = $3::numeric)
ORDER BY s.captured_at
"""

_FIXTURE_SQL = "SELECT home_id, away_id, kickoff_at FROM fixtures WHERE id = $1"

_FORM_SQL = """
SELECT tms.xg_for, tms.xg_against
FROM team_match_stats tms
JOIN fixtures f ON f.id = tms.fixture_id
WHERE tms.team_id = $1 AND f.status = 'finished' AND f.kickoff_at < $2
  AND tms.xg_for IS NOT NULL AND tms.xg_against IS NOT NULL
ORDER BY f.kickoff_at DESC
LIMIT $3
"""

_LEAGUE_SQL = """
SELECT tms.venue, avg(tms.xg_for) AS xg
FROM team_match_stats tms
JOIN fixtures f ON f.id = tms.fixture_id
WHERE f.status = 'finished' AND f.kickoff_at < $1 AND f.kickoff_at >= $2
  AND tms.xg_for IS NOT NULL
GROUP BY tms.venue
"""


def _line(args: dict[str, Any]) -> float | None:
    return args.get("line") if args["market"] == "totals" else None


async def _snapshots(conn: asyncpg.Connection, args: dict[str, Any]) -> list[asyncpg.Record]:
    return await conn.fetch(_SNAPSHOTS_SQL, args["fixture_id"], args["market"], _line(args))


def _latest(rows: list[asyncpg.Record], until: datetime | None = None) -> list[asyncpg.Record]:
    """Each (selection, bookmaker)'s most recent snapshot, optionally as it stood at `until`."""
    latest: dict[tuple[str, str], asyncpg.Record] = {}
    for row in rows:  # oldest first, so later rows replace earlier ones
        if until is None or row["captured_at"] <= until:
            latest = {**latest, (row["selection"], row["bookmaker"]): row}
    return list(latest.values())


def _best(rows: list[asyncpg.Record], selection: str) -> asyncpg.Record | None:
    """Highest price for a selection; ties go to the bookmaker shown first."""
    candidates = [r for r in rows if r["selection"] == selection]
    return min(candidates, key=lambda r: (-r["price"], r["sort_order"]), default=None)


def _price_pairs(label: str, got: dict[str, Any], best: asyncpg.Record | None) -> list[tuple]:
    if best is None:
        return [(label, "listed", "no price in odds_snapshots")]
    price = float(best["price"])
    return [
        (f"{label} best_price", got["best_price"], price, 0.0005),
        (f"{label} best_bookmaker", got["best_bookmaker"], best["display_name"]),
        (
            f"{label} implied_probability",
            got["implied_probability"],
            1 / price,
            PROBABILITY_TOLERANCE,
        ),
    ]


async def odds(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    latest = _latest(await _snapshots(conn, args))
    selections = {r["selection"] for r in latest}
    pairs: list[tuple] = [
        ("selections", sorted(s["selection"] for s in data["selections"]), sorted(selections))
    ]
    for got in data["selections"]:
        selection = got["selection"]
        quoted = sorted(
            (r["display_name"], float(r["price"])) for r in latest if r["selection"] == selection
        )
        pairs += [
            *_price_pairs(selection, got, _best(latest, selection)),
            (
                f"{selection} prices",
                sorted((p["bookmaker"], p["price"]) for p in got["prices"]),
                quoted,
            ),
        ]
    overround = sum(1 / float(_best(latest, s)["price"]) for s in selections)
    pairs += [("overround", data["overround"], overround, PROBABILITY_TOLERANCE)]
    return Expected(pairs, min((r["captured_at"] for r in latest), default=now))


def _direction(change_pct: float) -> str:
    if change_pct < -STABLE_CHANGE_PCT:
        return "steam"
    return "drift" if change_pct > STABLE_CHANGE_PCT else "stable"


async def odds_movement(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    selection = args["selection"]
    rows = [r for r in await _snapshots(conn, args) if r["selection"] == selection]
    since = now - timedelta(hours=args["hours"])
    sweeps = sorted({r["captured_at"] for r in rows if r["captured_at"] >= since})
    series = [float(_best(_latest(rows, until=sweep), selection)["price"]) for sweep in sweeps]
    if not series:
        return Expected([("series", "listed", "no prices in the window")], now)
    opening, current = series[0], series[-1]
    change_pct = (current - opening) / opening * 100
    pairs = [
        ("opening_price", data["opening_price"], opening, 0.0005),
        ("current_price", data["current_price"], current, 0.0005),
        ("change_pct", data["change_pct"], change_pct, 0.051),
        ("direction", data["direction"], _direction(round(change_pct, 1))),
        ("series", [p["best_price"] for p in data["series"]], series),
    ]
    return Expected(pairs, sweeps[-1])


def _mean(rows: list[asyncpg.Record], key: str) -> float:
    return sum(float(r[key]) for r in rows) / len(rows)


def _poisson(rate: float) -> list[float]:
    return [math.exp(-rate) * rate**k / math.factorial(k) for k in range(POISSON_GOALS + 1)]


def _probabilities(home_rate: float, away_rate: float, args: dict[str, Any]) -> dict[str, float]:
    home, away = _poisson(home_rate), _poisson(away_rate)
    cells = [(i, j, h * a) for i, h in enumerate(home) for j, a in enumerate(away)]

    def total(keep) -> float:
        return sum(p for i, j, p in cells if keep(i, j))

    if args["market"] == "h2h":
        return {
            "home": total(lambda i, j: i > j),
            "draw": total(lambda i, j: i == j),
            "away": total(lambda i, j: i < j),
        }
    if args["market"] == "totals":
        line = args["line"]
        return {"over": total(lambda i, j: i + j > line), "under": total(lambda i, j: i + j < line)}
    return {
        "yes": total(lambda i, j: i > 0 and j > 0),
        "no": total(lambda i, j: i == 0 or j == 0),
    }


async def compare_to_market(
    conn: asyncpg.Connection, now: datetime, args: dict[str, Any], data: dict[str, Any]
) -> Expected:
    fixture = await conn.fetchrow(_FIXTURE_SQL, args["fixture_id"])
    kickoff = fixture["kickoff_at"]
    home = await conn.fetch(_FORM_SQL, fixture["home_id"], kickoff, FORM_MATCHES)
    away = await conn.fetch(_FORM_SQL, fixture["away_id"], kickoff, FORM_MATCHES)
    league_rows = await conn.fetch(
        _LEAGUE_SQL, kickoff, kickoff - timedelta(days=LEAGUE_WINDOW_DAYS)
    )
    league = {r["venue"]: float(r["xg"]) for r in league_rows}
    league_mean = (league["home"] + league["away"]) / 2
    home_rate = (
        league["home"]
        * (_mean(home, "xg_for") / league_mean)
        * (_mean(away, "xg_against") / league_mean)
    )
    away_rate = (
        league["away"]
        * (_mean(away, "xg_for") / league_mean)
        * (_mean(home, "xg_against") / league_mean)
    )
    probabilities = _probabilities(home_rate, away_rate, args)
    latest = _latest(await _snapshots(conn, args))
    model = data["model"]
    pairs: list[tuple] = [
        ("expected_goals_home", model["expected_goals_home"], home_rate),
        ("expected_goals_away", model["expected_goals_away"], away_rate),
        ("matches_used", model["matches_used"], min(len(home), len(away))),
        ("label", data["label"], "estimate"),
    ]
    for got in data["selections"]:
        selection = got["selection"]
        best = _best(latest, selection)
        probability = probabilities[selection]
        pairs += [
            *_price_pairs(selection, got, best),
            (
                f"{selection} model_probability",
                got["model_probability"],
                probability,
                PROBABILITY_TOLERANCE,
            ),
        ]
        if best is not None:
            edge = probability - 1 / float(best["price"])
            pairs += [(f"{selection} edge", got["edge"], edge, PROBABILITY_TOLERANCE)]
    return Expected(pairs, min((r["captured_at"] for r in latest), default=now))
