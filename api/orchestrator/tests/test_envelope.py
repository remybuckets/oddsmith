from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.tools.envelope import (
    FRESHNESS_HOURS,
    ToolError,
    error_envelope,
    iso_utc,
    success,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_freshness_limits_match_spec():
    assert FRESHNESS_HOURS == {"odds": 6, "availability": 24, "stats": 48, "fixtures": 48}


def test_as_of_is_oldest_fetched_at_in_utc_z_format():
    older = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
    newer = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)

    result = success(
        source="API-Football", fetched_at=[newer, older], limit_hours=48, now=NOW, data={"x": 1}
    )

    assert result == {
        "ok": True,
        "source": "API-Football",
        "as_of": "2026-10-06T06:00:00Z",
        "is_stale": False,
        "freshness_limit_hours": 48,
        "warnings": [],
        "data": {"x": 1},
    }


def test_exactly_at_limit_is_not_stale():
    result = success(
        source="s", fetched_at=[NOW - timedelta(hours=6)], limit_hours=6, now=NOW, data={}
    )
    assert result["is_stale"] is False


def test_older_than_limit_is_stale():
    result = success(
        source="s",
        fetched_at=[NOW - timedelta(hours=6, seconds=1)],
        limit_hours=6,
        now=NOW,
        data={},
    )
    assert result["is_stale"] is True


def test_no_limit_is_never_stale():
    result = success(
        source="s", fetched_at=[NOW - timedelta(days=300)], limit_hours=None, now=NOW, data={}
    )
    assert result["is_stale"] is False
    assert result["freshness_limit_hours"] is None


def test_warnings_are_copied_into_a_list():
    result = success(
        source="s", fetched_at=[NOW], limit_hours=None, now=NOW, data={}, warnings=("a", "b")
    )
    assert result["warnings"] == ["a", "b"]


def test_success_requires_at_least_one_timestamp():
    with pytest.raises(ValueError):
        success(source="s", fetched_at=[], limit_hours=None, now=NOW, data={})


def test_iso_utc_converts_other_timezones():
    from datetime import timezone

    bst = timezone(timedelta(hours=1))
    assert iso_utc(datetime(2026, 10, 7, 13, 0, tzinfo=bst)) == "2026-10-07T12:00:00Z"


def test_error_envelope_shape():
    assert error_envelope(ToolError("not_found", "No such team.")) == {
        "ok": False,
        "error": {"code": "not_found", "message": "No such team."},
    }


def test_tool_error_rejects_unknown_codes():
    with pytest.raises(ValueError):
        ToolError("oops", "bad")
