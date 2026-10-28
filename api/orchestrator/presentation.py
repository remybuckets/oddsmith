"""How a tool result is shown to Claude: times in UK time, with the citation ready to copy.

Tool results keep UTC timestamps (contracts/README.md). Left to convert them, Claude showed
UTC kick-off times as UK times and cited the wrong as-of time, so the conversion happens
here. Cards, sources and the usage log are still built from the unchanged result.
"""

import re
from datetime import datetime
from typing import Any

from orchestrator.prompt import UK

MODEL_SOURCE_PREFIX = "Oddsmith model"
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|\+00:00)$")
_AGE_UNITS = (("day", 86400), ("hour", 3600), ("minute", 60))


def _uk(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp).astimezone(UK)


def uk_time(timestamp: str) -> str:
    """'2026-10-17T14:00:00Z' -> 'Sat 17 Oct 2026, 15:00'."""
    local = _uk(timestamp)
    return f"{local:%a} {local.day} {local:%b %Y, %H:%M}"


def _localised(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _localised(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_localised(value) for value in node]
    if isinstance(node, str) and _UTC_TIMESTAMP.match(node):
        return uk_time(node)
    return node


def _citation(source: str, as_of: str) -> str:
    label = MODEL_SOURCE_PREFIX if source.startswith(MODEL_SOURCE_PREFIX) else source
    local = _uk(as_of)
    return f"({label}, {local.day} {local:%b %H:%M})"


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}{'' if count == 1 else 's'}"


def age(as_of: str, now: datetime) -> str:
    """How old the data is in its two largest units, e.g. '1 day 1 hour' or '20 minutes'."""
    seconds = max(0, int((now - datetime.fromisoformat(as_of)).total_seconds()))
    parts: list[str] = []
    for unit, size in _AGE_UNITS:
        count, seconds = divmod(seconds, size)
        if count and len(parts) < 2:
            parts = [*parts, _plural(count, unit)]
    return " ".join(parts) or "under a minute"


def present(result: dict[str, Any], now: datetime) -> dict[str, Any]:
    """A copy of a tool result for Claude to read. Lookups (no freshness limit) lose their
    as_of, so a reference table's load time can't be cited as the age of a stat."""
    if not result.get("ok"):
        return result
    shown = _localised(result)
    if result["freshness_limit_hours"] is None:
        return {k: v for k, v in shown.items() if k not in ("as_of", "is_stale")}
    return {
        **shown,
        "cite_as": _citation(result["source"], result["as_of"]),
        "age": age(result["as_of"], now),
    }
