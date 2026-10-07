"""Parse a Server-Sent Events body into (event, data) pairs."""

import json
from typing import Any


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for frame in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events
