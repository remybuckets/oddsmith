"""Poisson goals model: expected goals from xG strengths, then market probabilities."""

import math

MAX_GOALS = 10  # per team; the mass beyond this is negligible and renormalised away


def expected_goals(
    *,
    home_for: float,
    home_against: float,
    away_for: float,
    away_against: float,
    league_home: float,
    league_away: float,
) -> tuple[float, float]:
    """Attack/defence strengths relative to the league's average xG per team per match,
    scaled by the league's home and away xG averages (the home adjustment)."""
    league_avg = (league_home + league_away) / 2
    home = league_home * (home_for / league_avg) * (away_against / league_avg)
    away = league_away * (away_for / league_avg) * (home_against / league_avg)
    return home, away


def _pmf(rate: float) -> list[float]:
    return [math.exp(-rate) * rate**k / math.factorial(k) for k in range(MAX_GOALS + 1)]


def score_matrix(home_rate: float, away_rate: float) -> list[list[float]]:
    """P(home scores i, away scores j), assuming independence, normalised to sum to 1."""
    home, away = _pmf(home_rate), _pmf(away_rate)
    raw = [[h * a for a in away] for h in home]
    total = sum(map(sum, raw))
    return [[p / total for p in row] for row in raw]


def _cells(matrix: list[list[float]]):
    return ((i, j, p) for i, row in enumerate(matrix) for j, p in enumerate(row))


def market_probabilities(
    matrix: list[list[float]], market: str, line: float | None
) -> dict[str, float]:
    if market == "h2h":
        return {
            "home": sum(p for i, j, p in _cells(matrix) if i > j),
            "draw": sum(p for i, j, p in _cells(matrix) if i == j),
            "away": sum(p for i, j, p in _cells(matrix) if i < j),
        }
    if market == "totals":
        return {
            "over": sum(p for i, j, p in _cells(matrix) if i + j > line),
            "under": sum(p for i, j, p in _cells(matrix) if i + j < line),
        }
    if market == "btts":
        yes = sum(p for i, j, p in _cells(matrix) if i > 0 and j > 0)
        return {"yes": yes, "no": 1 - yes}
    raise ValueError(f"unknown market: {market}")
