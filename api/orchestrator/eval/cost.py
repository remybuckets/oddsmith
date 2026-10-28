"""What an answer costs: each kind of token at its own price, summarised per model."""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from orchestrator.model_client import TurnUsage

TOKENS_PER_UNIT = 1_000_000
CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute cache writes cost 1.25x base input


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        return self.input * CACHE_WRITE_MULTIPLIER


# Anthropic list prices, October 2026 (DECISIONS.md #3 for input/output).
PRICES = {
    "claude-sonnet-5-5": Price(input=2.0, output=10.0, cache_read=0.20),
    "claude-opus-5-5": Price(input=4.0, output=20.0, cache_read=0.20),
}


def answer_cost(model: str, usage: TurnUsage) -> float:
    """USD for one answer. Raises KeyError for a model with no known price."""
    price = PRICES[model]
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / TOKENS_PER_UNIT


def counted_tokens(usage: TurnUsage) -> int:
    """What DAILY_TOKEN_BUDGET counts: all input (cached or not) plus output, unweighted."""
    return usage.total_input + usage.output_tokens


def cold_start(turns: Sequence[TurnUsage]) -> TurnUsage:
    """An answer's usage had the prompt cache been cold: the first turn's cache read becomes
    a cache write. The eval asks questions back to back, so it finds the system prompt and
    tools cached; a beta tester asking after a five-minute lull does not."""
    if not turns:
        return TurnUsage()
    first, *rest = turns
    cold_first = TurnUsage(
        input_tokens=first.input_tokens,
        output_tokens=first.output_tokens,
        cache_read_tokens=0,
        cache_write_tokens=first.cache_write_tokens + first.cache_read_tokens,
    )
    return sum(rest, cold_first)


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        raise ValueError("percentile() needs at least one value")
    rank = max(1, math.ceil(pct / 100 * len(values)))
    return sorted(values)[rank - 1]


def _model_summary(model: str, usages: list[TurnUsage]) -> dict[str, Any]:
    costs = [answer_cost(model, u) for u in usages]
    counted = [counted_tokens(u) for u in usages]
    return {
        "answers": len(usages),
        "mean_cost_usd": fmean(costs),
        "p95_cost_usd": percentile(costs, 95),
        "max_cost_usd": max(costs),
        "mean_input_tokens": round(fmean(u.input_tokens for u in usages)),
        "mean_cache_read_tokens": round(fmean(u.cache_read_tokens for u in usages)),
        "mean_cache_write_tokens": round(fmean(u.cache_write_tokens for u in usages)),
        "mean_output_tokens": round(fmean(u.output_tokens for u in usages)),
        "mean_counted_tokens": round(fmean(counted)),
        "p95_counted_tokens": round(percentile(counted, 95)),
    }


def summarise(records: Iterable[tuple[str, TurnUsage]]) -> dict[str, dict[str, Any]]:
    """Cost and token statistics per model, from (model, usage) per answer."""
    by_model: dict[str, list[TurnUsage]] = {}
    for model, usage in records:
        by_model = {**by_model, model: [*by_model.get(model, []), usage]}
    return {model: _model_summary(model, usages) for model, usages in by_model.items()}
