"""System prompt and the messages sent to Claude: recent history, then the dated question."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
MAX_HISTORY_TURNS = 12  # older turns are dropped to keep each question's cost flat

SYSTEM_PROMPT = (Path(__file__).with_name("system_prompt.md")).read_text(encoding="utf-8").strip()


def system_blocks() -> list[dict[str, Any]]:
    """The system prompt as one cached block; tools render before it, so they're cached too."""
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def history_messages(history: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """The last turns of the chat, non-empty, starting with a user turn as the API requires."""
    turns = [
        {"role": turn["role"], "content": turn["content"]}
        for turn in history
        if turn["content"].strip()
    ][-MAX_HISTORY_TURNS:]
    first_user = next((i for i, turn in enumerate(turns) if turn["role"] == "user"), len(turns))
    return turns[first_user:]


def question_message(question: str, now: datetime) -> dict[str, str]:
    """The date and time ride on the question, not the system prompt, so the prompt stays
    cached. The time matters: without it Claude can't tell today's finished matches from
    the ones still to kick off."""
    today = now.astimezone(UK)
    stamp = f"{today:%A} {today.day} {today:%B %Y}, {today:%H:%M}"
    return {"role": "user", "content": f"It is {stamp} UK time.\n\n{question}"}
