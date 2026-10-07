from decimal import Decimal

from orchestrator.tools.stats_math import per90, rate, sum_known


def test_rate_rounds_pct_to_one_decimal():
    assert rate(1, 3) == {"count": 1, "of": 3, "pct": 33.3}
    assert rate(2, 3) == {"count": 2, "of": 3, "pct": 66.7}


def test_rate_of_zero_is_zero_pct():
    assert rate(0, 0) == {"count": 0, "of": 0, "pct": 0.0}


def test_per90_rounds_to_two_decimals():
    assert per90(2, 265) == 0.68


def test_per90_with_no_minutes_is_zero():
    assert per90(3, 0) == 0.0


def test_sum_known_all_present():
    assert sum_known([Decimal("0.65"), Decimal("0.55")]) == (1.2, 0)


def test_sum_known_counts_missing_values():
    assert sum_known([Decimal("0.65"), None, Decimal("0.55")]) == (1.2, 1)


def test_sum_known_all_missing_is_none():
    assert sum_known([None, None]) == (None, 2)
