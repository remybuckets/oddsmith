"""A second opinion from Claude on each answer: is every claim backed by the tool results?

The number checks in figures.py can't tell a right figure on the wrong player from a right
one, so the judge reads the answer against the tool results claim by claim. Its verdicts
are advisory evidence for a person to review, not ground truth.
"""

import json
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import anthropic

from orchestrator.eval.checks import UK
from orchestrator.eval.grading import Finding
from orchestrator.presentation import present

logger = logging.getLogger(__name__)

MAX_TOKENS = 16000
FAILING_VERDICTS = frozenset({"wrong", "unsupported"})

SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "verdict": {"enum": ["supported", "derived", "wrong", "unsupported"]},
                    "reason": {"type": "string"},
                },
                "required": ["claim", "verdict", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

INSTRUCTIONS = """\
You are auditing one answer from Oddsmith, a Premier League betting research assistant. \
The assistant may only state figures that come from its tool results. Your job is to find \
every figure in the answer that is wrong.

Go through the answer and list each claim that carries a figure or a fact from the data: \
numbers, prices, percentages, counts, scores, league positions, dates, kick-off times, \
as-of times, bookmaker names, and injury or suspension statuses. For each claim give one \
verdict:

- supported: the tool results say exactly this, about this player, team, bookmaker, market \
and fixture, at the precision shown (rounding a longer decimal is fine).
- derived: not in the results as such, but correct simple arithmetic on them (a sum, a \
difference, a per-game average, a percentage, a price's implied probability, how old the \
data is). Check the arithmetic yourself before giving this verdict.
- wrong: contradicts the tool results, attaches a real figure to the wrong player, team, \
bookmaker, market, venue or period, or gets the arithmetic wrong.
- unsupported: appears nowhere in the tool results and cannot be worked out from them.

Rules:
- The tool results below are exactly what the assistant was shown: every time is already \
UK time (the clocks change on 25 October 2026, and that is already allowed for). A time in \
the answer must match the time in the results as written; don't convert anything yourself.
- Probabilities are stored as fractions (0.4082) and may be shown as percentages (40.8%).
- Numbers the user gave in the question, and general knowledge without figures, need no \
support. Saying the data is missing or a market is unavailable is not a claim to check, \
unless the tool results show the data was in fact there.
- These are fixed facts about the product, not claims to check: the GamCare helpline \
(0808 8020 133) and GAMSTOP, betting being for over-18s, the freshness limits (odds 6h, \
availability 24h, fixtures 48h, stats when a result is still missing 3h after \
kick-off), the limit of 8 tool calls per answer, the value model being a Poisson goals \
model on each team's last 10 matches of xG, adjusted for home advantage, team stats counting the team's own corners and cards, and every match in \
the data being Premier League.
- Don't judge style, tone or advice. Only list claims; if there are none, return an empty \
list. In `reason`, quote the tool value you compared against.
"""


def _prompt(record: Mapping[str, Any], now: datetime) -> str:
    calls = [
        {"tool": c["name"], "input": c["input"], "result": present(c["result"], now)}
        for c in record["tool_calls"]
        if not c.get("skipped")
    ]
    asked = now.astimezone(UK)
    history = "\n".join(f"{t['role']}: {t['content']}" for t in record.get("history", []))
    return (
        f"{INSTRUCTIONS}\n"
        f"<asked_at>{asked:%A %d %B %Y %H:%M} UK time (UTC{asked:%z})</asked_at>\n"
        f"<earlier_turns>\n{history}\n</earlier_turns>\n"
        f"<question>\n{record['question']}\n</question>\n"
        f"<tool_results>\n{json.dumps(calls, ensure_ascii=False)}\n</tool_results>\n"
        f"<answer>\n{record['text']}\n</answer>"
    )


async def judge_answer(
    client: anthropic.AsyncAnthropic, model: str, record: Mapping[str, Any], now: datetime
) -> list[dict[str, str]]:
    """The judge's claims for one answer: [{claim, verdict, reason}]."""
    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": _prompt(record, now)}],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"judge stopped with {response.stop_reason}")
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)["claims"]


def judge_finding(claims: list[dict[str, str]]) -> Finding:
    flagged = [
        f"{c['verdict']}: {c['claim']} ({c['reason']})"
        for c in claims
        if c["verdict"] in FAILING_VERDICTS
    ]
    return Finding("judge", not flagged, "; ".join(flagged))


async def judged(
    client: anthropic.AsyncAnthropic, model: str, record: Mapping[str, Any], now: datetime
) -> tuple[list[dict[str, str]], Finding]:
    """(claims, finding). A judge that cannot be reached is a failed check, not a pass."""
    if not record["text"]:
        return [], Finding("judge", True, "no answer text to judge")
    try:
        claims = await judge_answer(client, model, record, now)
    except (anthropic.APIError, RuntimeError, ValueError, StopIteration) as error:
        logger.exception("judge failed for %s", record.get("id"))
        return [], Finding("judge", False, f"judge call failed: {error}")
    return claims, judge_finding(claims)
