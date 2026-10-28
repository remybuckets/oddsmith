"""The envelope for finished-match data: player and team stats, league table, head-to-head.

A finished match's rows are loaded once and never re-fetched, so their fetched_at says
nothing about whether the data is current. Instead (decision 10) the data is as of the last
successful results sync, and stale only while a result is missing hours after kick-off.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import FRESHNESS_HOURS, iso_utc, success

RESULTS_JOB = "sync_results"
RESULT_GRACE_HOURS = 3  # a result may lag kick-off this long before the data counts as stale

_LAST_SYNC_SQL = """
SELECT max(finished_at) FROM job_runs WHERE name = $1 AND status = 'success'
"""

_MISSING_RESULT_SQL = """
SELECT EXISTS (
    SELECT 1 FROM fixtures
    WHERE kickoff_at < $1
      AND status NOT IN ('postponed', 'cancelled')
      AND (status <> 'finished' OR home_score IS NULL OR away_score IS NULL)
)
"""


async def results_success(
    ctx: ToolContext,
    *,
    source: str,
    fetched_at: Iterable[datetime],
    data: Mapping[str, Any],
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    """Build an ok envelope for finished-match data. Before any results sync has run (a
    database fresh from the backfill), the rows' own fetch times count, as for other data."""
    last_sync = await ctx.conn.fetchval(_LAST_SYNC_SQL, RESULTS_JOB)
    if last_sync is None:
        return success(
            source=source,
            fetched_at=fetched_at,
            limit_hours=FRESHNESS_HOURS["stats"],
            now=ctx.now,
            data=data,
            warnings=warnings,
        )
    cutoff = ctx.now - timedelta(hours=RESULT_GRACE_HOURS)
    return {
        "ok": True,
        "source": source,
        "as_of": iso_utc(last_sync),
        "is_stale": await ctx.conn.fetchval(_MISSING_RESULT_SQL, cutoff),
        "freshness_limit_hours": RESULT_GRACE_HOURS,
        "warnings": list(warnings),
        "data": dict(data),
    }
