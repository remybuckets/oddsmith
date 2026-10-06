# Oddsmith

**Read `SPEC.md` first.** It is the source of truth for MVP scope. If a request conflicts with the spec, flag it before building.

Then read `contracts/README.md`: it lists every cross-lane contract.

## Layout

| Path | What | Owner lane |
| --- | --- | --- |
| `SPEC.md` | MVP spec | lead |
| `contracts/` | API contract (OpenAPI + SSE), orchestrator interface | lead |
| `oddsmith_tools.json` | 11 tool schemas + result envelope | lead |
| `db/` | migrations (`db/migrate.sh`), Docker init | lead |
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
docker compose up -d                                              # Postgres 16 + pgvector on 5433, Redis on 6379
DATABASE_URL=postgresql://oddsmith:oddsmith@localhost:5433/oddsmith db/migrate.sh
```

Each lane runs its tests against its own database: `oddsmith_test_ingestion`, `oddsmith_test_orchestrator`, `oddsmith_test_backend` (same host and credentials). Ports: API 8000, web 3000.

## Conventions

- Python 3.12, `uv`, `ruff`, `pytest`. TypeScript strict, npm. Tests first; 80%+ coverage.
- Config from environment variables only (see `.env.example`). `.env` is gitignored; never commit secrets.
- Every number shown to a user must come from a tool result with a source and an as-of time.
- Users live in Supabase. Our Postgres stores the Supabase user id (uuid) but has no users table.
- Embeddings: Voyage AI, 1024 dimensions (`news_chunks.embedding`).
- Commits: `<type>: <description>` (feat, fix, refactor, docs, test, chore, perf, ci).
