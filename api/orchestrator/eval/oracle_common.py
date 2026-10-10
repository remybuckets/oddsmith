"""Shared by the oracles: what an oracle returns, and a few value helpers."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

PROBABILITY_TOLERANCE = 0.00015  # figures rounded to four decimals


@dataclass(frozen=True)
class Expected:
    """(label, tool value, SQL value[, tolerance]) pairs, and the oldest row SQL used."""

    pairs: list[tuple]
    oldest: datetime


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def number(value: Any) -> float | None:
    return None if value is None else float(value)


def rate_pairs(label: str, got: dict[str, Any], count: int, of: int) -> list[tuple]:
    pct = count / of * 100 if of else 0.0
    return [
        (f"{label}.count", got["count"], count),
        (f"{label}.of", got["of"], of),
        (f"{label}.pct", got["pct"], pct, 0.051),
    ]
