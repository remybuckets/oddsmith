"""Betting language Oddsmith never uses (SPEC.md): lock, banker, guaranteed, sure thing,
can't lose. The prompt bans it, questions that use it carry a reminder, and the eval checks
every answer for it."""

import re

_BANNED = re.compile(
    r"\b(locks?|bankers?|guaranteed|sure[- ]things?|can['’]?t lose)\b", re.IGNORECASE
)


def banned_terms(text: str) -> list[str]:
    return [m.group(0).lower() for m in _BANNED.finditer(text)]
