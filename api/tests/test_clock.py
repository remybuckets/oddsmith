from datetime import UTC, date, datetime

from app.clock import next_uk_midnight, uk_date


def test_uk_date_uses_london_time_not_utc():
    # 23:30 UTC on 10 Oct is 00:30 BST on 11 Oct
    assert uk_date(datetime(2026, 10, 10, 23, 30, tzinfo=UTC)) == date(2026, 10, 11)


def test_next_uk_midnight_during_bst():
    now = datetime(2026, 10, 10, 11, 0, tzinfo=UTC)
    assert next_uk_midnight(now) == datetime(2026, 10, 10, 23, 0, tzinfo=UTC)


def test_next_uk_midnight_during_gmt():
    now = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)
    assert next_uk_midnight(now) == datetime(2026, 11, 11, 0, 0, tzinfo=UTC)


def test_next_uk_midnight_across_clocks_going_back():
    # Clocks go back on Sunday 25 Oct 2026; Saturday midnight is still BST
    now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    assert next_uk_midnight(now) == datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
