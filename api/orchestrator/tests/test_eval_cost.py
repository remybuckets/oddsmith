import pytest

from orchestrator.eval.cost import answer_cost, counted_tokens, percentile, summarise
from orchestrator.model_client import TurnUsage

SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
USAGE = TurnUsage(
    input_tokens=1_000_000,
    output_tokens=100_000,
    cache_read_tokens=2_000_000,
    cache_write_tokens=400_000,
)


def test_cost_prices_each_token_kind_at_its_own_rate():
    # 1M input at $2, 0.1M output at $10, 2M cache reads at $0.20, 0.4M cache writes at $2.50.
    assert answer_cost(SONNET, USAGE) == pytest.approx(2.0 + 1.0 + 0.4 + 1.0)
    # Opus: $4 in, $20 out, $0.20 cache reads, $5 cache writes.
    assert answer_cost(OPUS, USAGE) == pytest.approx(4.0 + 2.0 + 0.4 + 2.0)


def test_cost_of_an_unknown_model_is_an_error():
    with pytest.raises(KeyError):
        answer_cost("claude-unknown", USAGE)


def test_counted_tokens_match_what_the_daily_budget_counts():
    # The backend budget adds tokens_in (cached included) and tokens_out, unweighted.
    assert counted_tokens(USAGE) == 3_500_000


def test_percentile_is_nearest_rank():
    values = [float(v) for v in range(1, 21)]

    assert percentile(values, 95) == 19.0
    assert percentile(values, 50) == 10.0
    assert percentile([7.0], 95) == 7.0


def test_percentile_of_nothing_is_an_error():
    with pytest.raises(ValueError):
        percentile([], 95)


def test_summarise_splits_cost_by_model():
    small = TurnUsage(input_tokens=1000, output_tokens=100)
    records = [(SONNET, small), (SONNET, small + small), (OPUS, small)]

    summary = summarise(records)

    assert set(summary) == {SONNET, OPUS}
    assert summary[SONNET]["answers"] == 2
    assert summary[SONNET]["mean_cost_usd"] == pytest.approx(0.003 * 1.5)
    assert summary[SONNET]["p95_cost_usd"] == pytest.approx(0.006)
    assert summary[SONNET]["mean_counted_tokens"] == 1650
    assert summary[OPUS]["mean_cost_usd"] == pytest.approx(0.006)
