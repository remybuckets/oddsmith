# Backend lane

You own `api/` **except `api/orchestrator/`** (orchestrator lane). Read `SPEC.md` ("API backend", "Compliance") and `contracts/openapi.yaml` first.

## Build

- FastAPI app in `api/app/`, implementing `contracts/openapi.yaml` exactly (paths, envelope, error codes, SSE event order).
- Auth: verify the Supabase access token (Bearer JWT) on every route except `/health` and `/fixtures/next`. The Supabase user id is the user id. Users live in Supabase — no users table in our Postgres.
- Gates before streaming, in order: authenticated → age confirmed → not on a break → per-IP rate limit (10/min) → daily question limit (15) → global daily token budget. Counters in Redis.
- `POST /conversations/{id}/messages`: call `orchestrator.answer()` (interface in `contracts/README.md`), emit `message_start` / `message_end` yourself, forward other events, persist the `usage` event's tool calls and tokens to `messages` and `usage_daily`. Never forward `usage`.
- Until the orchestrator lane merges, use a fake `answer()` in `api/app/` that yields canned contract-shaped events.
- `DELETE /me` removes the Supabase user and all their rows here.
- Sentry on errors; log detail server-side, return user-friendly messages.

## Rules

- `api/pyproject.toml` and `uv.lock` are shared with the orchestrator lane: add dependencies with `uv add`; on rebase conflicts, re-run `uv lock`.
- Tests use `oddsmith_test_backend` and a fake orchestrator; no real Claude calls in tests.
- Do not touch `api/orchestrator/`, `db/`, `contracts/`, `ingestion/`, `web/`. Need a contract change? Stop and tell the user.
