"""Routes that need no sign-in: /health and /fixtures/next."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from app.clock import to_iso
from app.current_user import DepsDep
from app.envelope import not_found, ok
from app.repos import fixtures, health
from app.repos.fixtures import FixtureRow

router = APIRouter()

MAX_SUGGESTED_QUESTIONS = 6
QUESTION_TEMPLATES = (
    "Who's injured for {home} vs {away}?",
    "Do {home} games usually go over 2.5?",
    "What's the best price on {home} to beat {away}?",
)
NO_FIXTURES_MESSAGE = "No upcoming fixtures yet. Check back soon."


def _fixture_json(row: FixtureRow) -> dict[str, Any]:
    return {
        "fixture_id": row.fixture_id,
        "matchweek": row.matchweek,
        "kickoff_at": to_iso(row.kickoff_at),
        "status": row.status,
        "home": asdict(row.home),
        "away": asdict(row.away),
        "home_score": row.home_score,
        "away_score": row.away_score,
    }


def suggested_questions(rows: list[FixtureRow]) -> list[str]:
    questions = [
        template.format(home=row.home.short_name, away=row.away.short_name)
        for row in rows
        for template in QUESTION_TEMPLATES
    ]
    return questions[:MAX_SUGGESTED_QUESTIONS]


@router.get("/health")
async def get_health(deps: DepsDep) -> dict[str, Any]:
    jobs = await health.job_health(deps.pool, deps.clock())
    status = "degraded" if any(job.is_stale for job in jobs) else "ok"
    return ok(
        {
            "status": status,
            "jobs": [
                {
                    "name": j.name,
                    "last_success_at": to_iso(j.last_success_at),
                    "is_stale": j.is_stale,
                }
                for j in jobs
            ],
        }
    )


@router.get("/fixtures/next")
async def get_next_fixtures(deps: DepsDep) -> dict[str, Any]:
    rows = await fixtures.next_matchweek(deps.pool, deps.clock())
    if not rows:
        raise not_found(NO_FIXTURES_MESSAGE)
    return ok(
        {
            "matchweek": rows[0].matchweek,
            "fixtures": [_fixture_json(row) for row in rows],
            "suggested_questions": suggested_questions(rows),
        }
    )
