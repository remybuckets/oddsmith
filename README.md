# Oddsmith

*The tipster the bookies would send off.*

Oddsmith is an AI chatbot that answers pre-match betting questions about the Premier League with live, cited stats, injuries and odds. It gives a view, not a tip: every number comes from a data source with an as-of time, and it never sells a "lock".

**Status:** in development. The private beta is planned for 14 October 2026; nothing is deployed yet. Current state is in [`HANDOFF.md`](HANDOFF.md).

## What it answers

- "How has Saka done away from home this season?"
- "Who's injured for Villa vs Spurs?"
- "Do Brentford games usually go over 2.5?"
- "What's the best price on Newcastle to win?"
- "Is there value in Newcastle to win?"

The MVP covers the Premier League 2026/27 only, as a mobile-friendly web chat. It takes no bets and has no affiliate links. Full scope: [`SPEC.md`](SPEC.md).

## How it works

Data flows one way. Scheduled workers pull from the providers into Postgres; Claude reads only the database, through a fixed set of tools, and never calls a provider or writes SQL.

```
API-Football, The Odds API
          │
   Ingestion workers          scheduled jobs, idempotent upserts
          │
  Supabase Postgres + Redis   stats, fixtures, odds, users; limits and cache
          │
  Orchestrator (Claude)       tool-use loop, every figure cited
          │
   FastAPI backend            auth, 18+ gate, limits, SSE streaming
          │
   Next.js chat app           stat, odds and value cards in answers
```

**Stack:** Python 3.12, FastAPI, Supabase (Postgres 17 + Auth), Redis, Claude via the Anthropic API (Sonnet 5.5 by default, Opus 5.5 for value questions), Next.js, Tailwind, shadcn/ui, Sentry.

## Repository layout

| Path | What |
| --- | --- |
| [`SPEC.md`](SPEC.md) | MVP spec: the source of truth for scope |
| [`DECISIONS.md`](DECISIONS.md) | Settled decisions that override older wording in the spec |
| [`HANDOFF.md`](HANDOFF.md) | Current status, local environment, routines |
| [`contracts/`](contracts/README.md) | HTTP + SSE API (OpenAPI) and the orchestrator interface |
| `oddsmith_tools.json` | Tool schemas and the result envelope |
| `supabase/migrations/` | Database migrations |
| `ingestion/` | Scheduled workers: providers → Postgres |
| `api/orchestrator/` | Tool implementations, Claude tool-use loop, system prompt |
| `api/` | FastAPI: auth, limits, SSE, persistence |
| `web/` | Next.js chat app |

## Local setup

You need Docker, the [Supabase CLI](https://supabase.com/docs/guides/cli), [`uv`](https://docs.astral.sh/uv/) and Node with npm 11.

```bash
cp .env.example .env      # then fill in the keys; `supabase status` prints the local Supabase ones
supabase start            # Postgres (54322), Auth API (54321), Studio (54323), email inbox (54324)
supabase db reset         # apply supabase/migrations/
docker compose up -d      # Redis on 6379
```

The API and the ingestion workers read the repo-root `.env`. The web app needs the `NEXT_PUBLIC_*` values in its own environment (for example `web/.env.local`).

### Run

```bash
# API on http://localhost:8000
cd api && uv run uvicorn app.main:create_app --factory --port 8000

# Web on http://localhost:3000
cd web && npx npm@11 install && npm run dev

# Ingestion: one job at a time (uses API-Football and Odds API quota)
cd ingestion && uv run python -m oddsmith_ingestion.cli seed_reference
```

Ingestion jobs and the first-load order are in [`ingestion/DEPLOY.md`](ingestion/DEPLOY.md).

### Test

```bash
db/test-db.sh <ingestion|orchestrator|backend|lead>   # builds a test database and prints its URL

cd api && uv run pytest -q && uv run ruff check
cd ingestion && uv run pytest -q && uv run ruff check
cd web && npm test && npm run typecheck && npm run check:api
```

## Deployment

Supabase hosts the database and auth, Railway runs the API, the ingestion cron and Redis, and Vercel serves the web app. Runbooks: [`api/DEPLOY.md`](api/DEPLOY.md) and [`ingestion/DEPLOY.md`](ingestion/DEPLOY.md).

## Responsible gambling

Oddsmith is for adults (18+) in Great Britain. It publishes information and estimates, not advice. If gambling is causing you problems, call GamCare free on 0808 8020 133 or register with [GAMSTOP](https://www.gamstop.co.uk).

## Contributing

Work is split into lanes, each owning part of the tree. Rules and conventions are in [`CLAUDE.md`](CLAUDE.md).
