# Handoff

Where the project stands and how to pick it up. **Update the "Status" and "Log" sections at the end of every lead-lane session.** Rules live in `CLAUDE.md`, scope in `SPEC.md`, settled choices in `DECISIONS.md`. This file is for what those don't cover.

## Status (as of end of 2026-10-07, build day 2)

**Everything committed on all four lanes is merged to `main` (`a532dd0` and after), and every lane branch is rebased on it.** On `main`: api 211 tests (backend + orchestrator), ingestion 157, web 47 + typecheck; ruff clean.

| Lane | On `main` | Pick up tomorrow |
| --- | --- | --- |
| **Ingestion** | Provider clients (retries, quota guard); recorded fixtures; all beta jobs: `seed_reference`, `sync_fixtures`, `sync_results` (batched on Pro), `backfill_season`, `sync_availability`, `sync_odds` + `sync_btts`; `cli tick` for a 30-minute cron that runs whatever is due (advisory lock stops overlapping runs); 157 tests, 95% coverage | Deploy the worker as a Railway cron `*/30 * * * *` running `uv run python -m oddsmith_ingestion.cli tick` from `ingestion/` (only after the Odds API plan upgrade); run `backfill_season` + `seed_reference` against the hosted database; watch Odds API credits |
| **Orchestrator** | Tool registry (validates against `oddsmith_tools.json`, hides `search_news` while news is off); envelope with freshness limits; 7 read tools: `resolve_entity`, player/team stats, H2H, fixtures, league table, availability | `get_odds`, `get_odds_movement`, `compare_to_market`. Local dev DB has 427 odds rows (20 fixtures × 8 bookmakers, captured 2026-10-07 22:11 UTC). Totals is only line 2.5, often from 1 bookmaker; BTTS rows exist only within 48h of kick-off; read `odds_latest` for current prices (`captured_at` = our fetch time); Claude tool-use loop (Sonnet default, Opus for value questions); system prompt; **export `answer()` from `api/orchestrator/__init__.py`**. Backend's `load_answer()` picks it up automatically and drops the fake |
| **Backend** | Full `contracts/openapi.yaml`: auth (Supabase JWKS), profiles, gates, SSE chat, persistence, feedback, `/health`, `/fixtures/next`; every response and event validated against the contract in tests; Dockerfile (build from repo root: `docker build -f api/Dockerfile .`) + `railway.json` | Integration test with the real `answer()` once orchestrator exports it; Railway deploy (set `CORS_ALLOWED_ORIGINS`, `FORWARDED_ALLOW_IPS`); Sentry DSN by day 8 |
| **Web** | Next.js 16 scaffold; generated API types (`npm run check:api` catches drift); typed API client (`openapi-fetch`) with handling for all 9 error codes; UK time formatting; MSW test server | The UI: magic-link login, 18+ onboarding, chat with SSE streaming, stat/odds/value cards, conversation list, take-a-break, delete account. Its last session ended asking "Shall I start?" on the UI |

**Fixed on `main` today:**
- OpenAPI discriminator mappings.
- `.gitignore` for Python/Node artefacts.
- API-Football Pro (decision 7) and its season env vars.
- `CORS_ALLOWED_ORIGINS` and `FORWARDED_ALLOW_IPS` added to `.env.example`.
- `api/uv.lock` rebuilt after git's line merge corrupted it.
- `db/test-db.sh lead` gives the lead lane its own test database (`ORCHESTRATOR_TEST_DATABASE_URL` / `INGESTION_TEST_DATABASE_URL` / `TEST_DATABASE_URL` point a suite at it). Sharing a lane's test database while that lane runs tests causes deadlocks.

**Start of day for every lane:** `git rebase main`, then re-run `db/test-db.sh <lane>`.

**Lead lane tomorrow:**
1. **The Odds API is still on the free 500-credit tier** (492 left). The cron needs about 3–3.5k credits a month, so buy the 20K plan before ingestion's cron goes live.
2. Settle what's under "Still open" below, especially `DAILY_TOKEN_BUDGET` and `VALUE_EDGE_THRESHOLD`: backend's budget gate and orchestrator's `compare_to_market` both need them.
3. After any merge into `api/`, run `uv lock --locked` in `api/`. If the lockfile is broken, rebuild it from one side's `uv.lock` with `uv lock`, as done today.

## Which session are you?

| Folder | Branch | You are | First read |
| --- | --- | --- | --- |
| `~/Desktop/oddsmith` | `main` | **Lead**: contracts, migrations, reviews, merges | this file |
| `~/Desktop/oddsmith-ingestion` | `lane/ingestion` | Ingestion lane | `ingestion/CLAUDE.md` |
| `~/Desktop/oddsmith-orchestrator` | `lane/orchestrator` | Orchestrator lane | `api/orchestrator/CLAUDE.md` |
| `~/Desktop/oddsmith-backend` | `lane/backend` | Backend lane (works in `api/`, not a `backend/` folder) | `api/CLAUDE.md` |
| `~/Desktop/oddsmith-web` | `lane/web` | Web lane | `web/CLAUDE.md` |

Check with `git branch --show-current` if unsure.

**Kickoff prompt for a lane session:**

> You're the <lane> lane. Read CLAUDE.md, SPEC.md, DECISIONS.md, HANDOFF.md and your folder's CLAUDE.md, then start. Work test-first and commit to your branch as you go.

## Local environment

| Thing | Where | Notes |
| --- | --- | --- |
| Supabase (local) | API http://127.0.0.1:54321, Postgres 54322, Studio http://127.0.0.1:54323, email inbox http://127.0.0.1:54324 | Start/stop from `~/Desktop/oddsmith` only: `supabase start`, `supabase stop` |
| Redis | localhost:6379 | `docker compose up -d` |
| Lane test databases | same Postgres, `oddsmith_test_<lane>` | `db/test-db.sh <lane>`; re-run after every new migration |
| `.env` | main repo only; each worktree has a symlink to it | Points at **local** Supabase. Gitignored |
| `.env.production` | main repo | Hosted Supabase URL and keys. Gitignored. Copy into Railway/Vercel when deploying |

**Known quirks:**

- **Another local Supabase project (`supabase-initial`) uses the same ports.** Only one can run at a time. If `supabase start` fails with "port is already allocated", run `supabase stop --project-id supabase-initial` (its data is kept).
- **Homebrew Postgres owns port 5432.** Ours is on 54322; don't change that.
- **Local Python is 3.14; the project pins 3.12.** Always go through `uv`, which fetches 3.12.
- **A GateGuard hook** blocks the first Bash command, the first write to each new file, and anything that looks destructive, until you state facts about it. Answer the facts it asks for, then retry the same call.
- **Web needs npm 11.** Global npm 10.9 crashes installing `web/` ("Cannot read properties of null (reading 'edgesOut')"). Use `npx npm@11 install`. Vitest 5 needs `@types/node` ^22. `npm run check:api` fails if the generated types drift from `contracts/openapi.yaml`.
- **A cost hook** reports session spend. When it says critical, tell the user before continuing.

## Lead-lane routines

**Merge a lane:**
```bash
git -C ../oddsmith-<lane> log --oneline main..HEAD   # what's new
git merge --no-ff lane/<lane>                          # from ~/Desktop/oddsmith on main
# run that lane's tests, then bring the other lanes up to date:
for l in ingestion orchestrator backend web; do git -C ../oddsmith-$l rebase main; done
```
Merge a lane only when its tests pass. If a rebase or merge touches `uv.lock`, check it with `uv lock --locked`; if broken, restore one side's lock and re-run `uv lock`. Run the lead's test runs against `db/test-db.sh lead`, not a lane's database.

**Change the schema:** add a new file `supabase/migrations/<YYYYMMDDHHMMSS>_<name>.sql` (never edit an applied one) → `supabase db reset` locally → commit on `main` → lanes rebase and re-run `db/test-db.sh`.

**Add a bookmaker:** a migration with `INSERT INTO bookmakers (key, display_name, sort_order) VALUES (...)`. Keys come from The Odds API's bookmaker list. Up to 10 enabled bookmakers cost the same; the 11th doubles odds credits.

**Change a contract** (`oddsmith_tools.json`, `contracts/`): edit on `main`, validate, commit, tell the affected lanes to rebase.

## Still open

From `SPEC.md` and later discussion; settle them here and record the result in `DECISIONS.md`:

- **Before the beta:** daily token budget (£); value-badge edge threshold; domain and magic-link email sender (Supabase's built-in email sends only a few per hour); how long chat messages are kept.
- **From the spec:** player props source; value model now or after the beta; beta size (about 20 or about 100).
- **To do:** data licence checks for API-Football and The Odds API; Supabase Pro on the hosted project before beta day; Sentry DSN by day 8.

## Log

Newest first. One line per lead-lane session: date, what changed, commit.

- **2026-10-07 (end of day):** Merged ingestion (availability, odds, BTTS, cron tick), orchestrator (tool layer), backend (contract tests, Docker/Railway) and web (API client); rebuilt `api/uv.lock`; added missing env vars and `db/test-db.sh lead`; rebased all lanes.
- **2026-10-07 (later):** Merged web (scaffold + generated types). Merged ingestion (`b731666`) and backend (`f481f0f`); rebased ingestion, backend and web. Fixed on `main`: OpenAPI discriminator mappings, `.gitignore`, API-Football Pro decision + season env vars.
- **2026-10-07:** Applied decisions: everything on Supabase, profiles table, Sonnet 5.5/Opus 5.5, voyage-4, news deferred, 8 bookmakers (`c3eddcb`). Ran `supabase init`, local stack up, `.env` points at local and hosted values are in `.env.production` (`92c3984`).
- **2026-10-06:** Repo scaffold; Phase 0 contracts (schema, 11 tool schemas, OpenAPI + SSE, lane CLAUDE.md files); four lane worktrees (`46af2c0`).
