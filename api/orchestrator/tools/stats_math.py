"""Small numeric helpers shared by the stats tools."""

from collections.abc import Iterable
from decimal import Decimal

MINUTES_PER_MATCH = 90


def rate(count: int, of: int) -> dict[str, int | float]:
    """A `rate` object from the tool contract: count of `of`, with pct to one decimal."""
    pct = round(count / of * 100, 1) if of else 0.0
    return {"count": count, "of": of, "pct": pct}


def per90(total: float | Decimal, minutes: int) -> float:
    if not minutes:
        return 0.0
    return round(float(total) / minutes * MINUTES_PER_MATCH, 2)


def as_float(value: Decimal | int | None) -> float | None:
    return None if value is None else float(value)


def missing_warning(label: str, missing: int, of: int) -> list[str]:
    """A warning such as 'xG missing for 1 of 3 matches', or none if nothing is missing."""
    return [f"{label} missing for {missing} of {of} matches"] if missing else []


def sum_known(values: Iterable[Decimal | int | None]) -> tuple[float | None, int]:
    """Sum the non-null values. Returns (total, or None if all missing; number missing)."""
    items = list(values)
    known = [v for v in items if v is not None]
    total = float(sum(known, Decimal(0))) if known else None
    return total, len(items) - len(known)
