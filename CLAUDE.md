# Oddsmith

**Read `SPEC.md` first.** It is the source of truth for MVP scope. If a request conflicts with the spec, flag it before building.

Then read `DECISIONS.md` (settled decisions that override older wording in the spec) and `contracts/README.md` (every cross-lane contract).

## Layout

| Path | What | Owner lane |
| --- | --- | --- |
| `SPEC.md` | MVP spec | lead |
| `contracts/` | API contract (OpenAPI + SSE), orchestrator interface | lead |
| `oddsmith_tools.json` | 11 tool schemas + result envelope | lead |
| `DECISIONS.md` | settled decisions log | lead |
| `supabase/migrations/` | database migrations (Supabase CLI) | lead |
| `db/test-db.sh` | builds a lane's test database | lead |
| `ingestion/` | 7 scheduled workers: providers → Postgres | ingestion |
| `api/orchestrator/` | tool implementations, Claude tool-use loop, system prompt | orchestrator |
| `api/` (everything else) | FastAPI: auth, limits, SSE, persistence | backend |
| `web/` | Next.js chat app | web |

## Parallel lanes

Each lane runs in its own git worktree on branch `lane/<name>`; the lead lane works on `main` in `~/Desktop/oddsmith`.

- **Only edit files your lane owns.** Need a change elsewhere (schema, contract, another lane's code)? Stop and ask the user to raise it with the lead lane.
- **Never edit an applied migration or a contract file from a lane branch.**
- Merge to `main` only via the lead lane. Rebase on `main` at the start of each day.
- Only the ingestion lane calls API-Football or The Odds API (100 req/day free tier). Other lanes use recorded responses in `ingestion/tests/fixtures/` or their own test data.

## Local setup

```bash
supabase start            # local Postgres + pgvector (54322), Auth API (54321), Studio (54323), email inbox (54324)
supabase db reset         # re-apply supabase/migrations/ to the local dev database
docker compose up -d      # Redis on 6379
```

Only the lead lane runs `supabase start` / `db reset`; the stack is shared by all worktrees. Each lane tests against its own database, built with `db/test-db.sh <ingestion|orchestrator|backend>` (prints its URL; re-run after any new migration). Ports: API 8000, web 3000.

Production: `supabase link` then `supabase db push`. Python connects through the session pooler or directly, never the transaction pooler (breaks asyncpg prepared statements).

## Conventions

- Python 3.12, `uv`, `ruff`, `pytest`. TypeScript strict, npm. Tests first; 80%+ coverage.
- Config from environment variables only (see `.env.example`). `.env` is gitignored; never commit secrets.
- Every number shown to a user must come from a tool result with a source and an as-of time.
- Everything lives in one Supabase Postgres. `profiles.id` = `auth.users.id`; user-owned rows cascade from `profiles`.
- RLS is enabled on every table with no policies: only server-side connections can read or write. Never add a policy or expose a table to the browser without the lead lane.
- Claude: `CLAUDE_MODEL_FAST` (Sonnet 5.5) by default, `CLAUDE_MODEL_STRONG` (Opus 5.5) for value questions.
- News is off for the beta (`NEWS_ENABLED=false`). Embeddings later: Voyage `voyage-4`, 1024 dims.
- Commits: `<type>: <description>` (feat, fix, refactor, docs, test, chore, perf, ci).
