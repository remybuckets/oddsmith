"""The result envelope every tool returns (see `envelope` in oddsmith_tools.json)."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

# Freshness limits in hours, from SPEC.md. Beyond these a result is flagged stale.
FRESHNESS_HOURS = {"odds": 6, "availability": 24, "stats": 48, "fixtures": 48}

ERROR_CODES = frozenset({"invalid_input", "not_found", "no_data", "unsupported", "internal"})

SOURCE_API_FOOTBALL = "API-Football"


class ToolError(Exception):
    """A failure that is safe to show Claude. `message` must never contain SQL or internals."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown tool error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def success(
    *,
    source: str,
    fetched_at: Iterable[datetime],
    limit_hours: int | None,
    now: datetime,
    data: Mapping[str, Any],
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    """Build an ok envelope. `as_of` is the oldest of `fetched_at`, the rows the answer used."""
    timestamps = list(fetched_at)
    if not timestamps:
        raise ValueError("success() needs at least one fetched_at timestamp")
    as_of = min(timestamps)
    is_stale = limit_hours is not None and now - as_of > timedelta(hours=limit_hours)
    return {
        "ok": True,
        "source": source,
        "as_of": iso_utc(as_of),
        "is_stale": is_stale,
        "freshness_limit_hours": limit_hours,
        "warnings": list(warnings),
        "data": dict(data),
    }


def error_envelope(error: ToolError) -> dict[str, Any]:
    return {"ok": False, "error": {"code": error.code, "message": error.message}}
