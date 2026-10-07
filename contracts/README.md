# Contracts

Everything that two lanes both depend on lives here or is listed here. Only the lead lane changes these, on `main`; lanes then rebase.

| Contract | File | Between |
| --- | --- | --- |
| Database schema | `supabase/migrations/*.sql` | everyone |
| Tool schemas | `oddsmith_tools.json` | tools ↔ Claude loop (both in the orchestrator lane), ingestion data shape |
| HTTP + SSE API | `contracts/openapi.yaml` | backend ↔ web |
| Orchestrator interface | this file, below | orchestrator ↔ backend |

## Orchestrator interface (Python)

The backend calls one async generator. It owns limits, persistence, `message_start` and `message_end`; the orchestrator owns tools, Claude calls and everything in between.

```python
# api/orchestrator/__init__.py
from collections.abc import AsyncIterator
from typing import Literal, TypedDict

class ChatTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str

async def answer(history: list[ChatTurn], question: str) -> AsyncIterator[dict]:
    """Yield events in this order:
       - any number of tool_status / text_delta / card events (shapes: contracts/openapi.yaml)
       - exactly one `sources` event
       - exactly one final `usage` event (backend persists it, never forwards it):
         {"type": "usage", "model": str, "tokens_in": int, "tokens_out": int,
          "tool_calls": [{"tool", "input", "source", "as_of", "is_stale", "duration_ms", "error"}]}
       On failure, yield {"type": "error", "error": {"code": "internal", "message": ...}} and stop.
    """
```

Until the orchestrator lane merges, the backend lane uses a fake `answer()` that yields canned events matching these shapes.

## Tool results

Every tool returns the `envelope` defined in `oddsmith_tools.json`; `output_schema` describes `envelope.data`. Only `name`, `description` and `input_schema` are sent to Claude.

## Conventions

- Internal Postgres ids everywhere outside ingestion; provider ids never leave `ingestion/`.
- Timestamps: ISO 8601 UTC in data and on the wire; Europe/London only when rendering.
- Odds: decimal prices. Markets `h2h | totals | btts`; selections `home | draw | away | over | under | yes | no`.
- Users: the Supabase Auth user id (uuid) is the user id; `profiles` holds our per-user settings.
- Bookmakers: `odds_snapshots.bookmaker` is a `bookmakers.key`; show `display_name`, in `sort_order`.
