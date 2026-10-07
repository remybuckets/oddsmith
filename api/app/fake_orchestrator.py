"""Stand-in for orchestrator.answer() until the orchestrator lane merges. Canned, contract-shaped."""

from collections.abc import AsyncIterator
from typing import Any

from app.orchestrator_port import ChatTurn

FAKE_MODEL = "fake-orchestrator"
_SOURCE = {"source": "API-Football", "as_of": "2026-10-10T09:00:00Z", "is_stale": False}


async def answer(history: list[ChatTurn], question: str) -> AsyncIterator[dict[str, Any]]:
    yield {
        "type": "tool_status",
        "tool": "resolve_entity",
        "status": "started",
        "label": "Looking that up",
    }
    yield {
        "type": "tool_status",
        "tool": "resolve_entity",
        "status": "finished",
        "label": "Looking that up",
    }
    yield {"type": "text_delta", "text": "This is a placeholder answer "}
    yield {"type": "text_delta", "text": "until the orchestrator is connected."}
    yield {
        "type": "card",
        "card": {
            "card_type": "stat",
            "title": "Placeholder",
            "columns": ["Stat", "Value"],
            "rows": [["Questions in this chat", len(history) // 2 + 1]],
            "form": None,
            "source": _SOURCE,
        },
    }
    yield {"type": "sources", "sources": [_SOURCE]}
    yield {
        "type": "usage",
        "model": FAKE_MODEL,
        "tokens_in": 120 + len(question),
        "tokens_out": 40,
        "tool_calls": [
            {
                "tool": "resolve_entity",
                "input": {"query": question[:50]},
                "source": "API-Football",
                "as_of": _SOURCE["as_of"],
                "is_stale": False,
                "duration_ms": 12,
                "error": None,
            }
        ],
    }
