"""Time helpers. Daily limits reset at UK midnight; everything is stored and sent in UTC."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


def uk_date(now: datetime) -> date:
    return now.astimezone(UK).date()


def next_uk_midnight(now: datetime) -> datetime:
    tomorrow = uk_date(now) + timedelta(days=1)
    return datetime.combine(tomorrow, time(0), tzinfo=UK).astimezone(UTC)


def to_iso(moment: datetime | None) -> str | None:
    """ISO 8601 UTC with a Z suffix, as the contract uses on the wire."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
