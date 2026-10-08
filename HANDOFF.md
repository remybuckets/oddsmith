# Handoff

Where the project stands and how to pick it up. **Update the "Status" and "Log" sections at the end of every lead-lane session.** Rules live in `CLAUDE.md`, scope in `SPEC.md`, settled choices in `DECISIONS.md`. This file is for what those don't cover.

## Status (as of 2026-10-08, build day 3)

**All four lanes' committed work is merged to `main` (`b6186b0`). The real orchestrator is wired into the backend: no more fake.** On `main`: api 314 tests (backend + orchestrator, ruff clean), ingestion 180, web 173 + typecheck + `next build` (9 routes).

| Lane | On `main` | Pick up next |
| --- | --- | --- |
| **Ingestion** | Provider clients (retries, quota guard); all beta jobs with a `lean` odds cadence (decision 8); `cli tick` (30-minute cron, advisory lock); `cli check` (matchweek health report); Sentry with provider keys scrubbed; `ingestion/Dockerfile` + `railway.json`; `ingestion/DEPLOY.md`. MW6 live check 2026-10-08: 0 problems | **Deploy the cron to Railway before Sat 10 Oct** (option 1, chosen 2026-10-08), first load on the hosted DB (~110 API-Football requests), then the MW6 runbook in `DEPLOY.md` |
| **Orchestrator** | All 10 beta tools incl. `get_odds`, `get_odds_movement`, `compare_to_market`; Claude tool-use loop (max 8 tool calls, Opus for value questions, prompt caching); system prompt in its own file; stat/odds/value cards validated against the contract; `answer()` exported and used by backend | **Day 7 eval:** a 50-question eval set run against real data; fix every wrong figure; guardrail tests (no "locks", estimates labelled, under-18 / break flows). Measure real cost per answer to re-set `DAILY_TOKEN_BUDGET` |
| **Backend** | Full contract; real orchestrator; Sentry; stale-job alerts; `api/scripts/smoke.py`; `api/DEPLOY.md`; Dockerfile + `railway.json` | Deploy the API to Railway after the hosted DB exists; run the smoke script against it; set `CORS_ALLOWED_ORIGINS` to the web URL |
| **Web** | Every screen: landing, magic-link sign-in + callback, 18+ onboarding, chat (fixture strip, streaming answers, stat/odds/value cards, feedback, chat list), settings (usage, take-a-break, delete account), draft terms + privacy; copy test blocks "lock/banker/guaranteed/sure thing" | Deploy to Vercel (needs `NEXT_PUBLIC_*`; the build fails without them, by design); end-to-end Playwright run against the local stack; terms and privacy are **drafts pending review** |

**Deploy (option 1), what's needed from the user:**
1. `! supabase login`, plus the hosted project's **database password** (for `supabase link` + `db push`, and the session-pooler `DATABASE_URL`, which isn't in `.env.production` yet).
2. `! railway login` (CLI installed 2026-10-08, v5.64.0), then create or choose the Railway project.
3. A **Sentry DSN** (optional for the weekend; needed by day 8).
4. Later, for the beta: a Vercel account for web, and a custom email sender for magic links (Supabase's built-in sends only a few per hour).

Then the lead lane pushes the schema to the hosted DB, ingestion deploys the cron and runs the first load, and backend deploys the API.

**Fixed on `main` (2026-10-07/08):**
- OpenAPI discriminator mappings.
- `.gitignore` for Python/Node artefacts.
- API-Football Pro (decision 7) and its season env vars.
- `CORS_ALLOWED_ORIGINS` and `FORWARDED_ALLOW_IPS` added to `.env.example`.
- `api/uv.lock` rebuilt after git's line merge corrupted it.
- Backend wiring tests updated for the real `answer()`; the fallback to the fake is still tested.
- `db/test-db.sh lead` gives the lead lane its own test database (`ORCHESTRATOR_TEST_DATABASE_URL` / `INGESTION_TEST_DATABASE_URL` / `TEST_DATABASE_URL` point a suite at it). Sharing a lane's test database while that lane runs tests causes deadlocks.

**Deploy notes (from ingestion):**
- **Railway variables must be bare values.** Don't paste lines from `.env`: its inline `# comments` become part of the value and break e.g. `API_FOOTBALL_SEASON`.
- **Hosted `DATABASE_URL`** must use the Supabase **session pooler** with `?sslmode=require` (never the transaction pooler).
- **Before any deploy:** install the Railway CLI (`brew install railway`, then `railway login`), `supabase link` + `supabase db push` to the hosted project (lead lane), and a Sentry DSN (API and worker both read `SENTRY_DSN`).

**Start of day for every lane:** `git rebase main`, then re-run `db/test-db.sh <lane>`.

**Lead lane notes:**
1. **The Odds API stays on the free tier until there's a working model** (decision 8). Upgrading later means buying the 20K plan and setting `ODDS_CADENCE=full`.
2. Settle what's under "Still open" below. Token budget and edge threshold are settled (decision 9); re-set the budget on day 7 from the eval's measured cost.
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
- **The ECC plugin's cost hook** (`post:ecc-context-monitor`, `stop:cost-tracker`) reports session spend. The user doesn't want it relayed: ignore it and don't stop work over it.

## Lead-lane routines

**Merge a lane:**
```bash
git -C ../oddsmith-<lane> log --oneline main..HEAD   # what's new
git merge --no-ff <tested commit hash>                 # from ~/Desktop/oddsmith on main; merge the hash you tested, not lane/<lane>, since a busy lane can commit in between
# run that lane's tests, then bring the other lanes up to date:
for l in ingestion orchestrator backend web; do git -C ../oddsmith-$l rebase main; done
```
Merge a lane only when its tests pass. If a rebase or merge touches `uv.lock`, check it with `uv lock --locked`; if broken, restore one side's lock and re-run `uv lock`. Run the lead's test runs against `db/test-db.sh lead`, not a lane's database.

**Change the schema:** add a new file `supabase/migrations/<YYYYMMDDHHMMSS>_<name>.sql` (never edit an applied one) → `supabase db reset` locally → commit on `main` → lanes rebase and re-run `db/test-db.sh`.

**Add a bookmaker:** a migration with `INSERT INTO bookmakers (key, display_name, sort_order) VALUES (...)`. Keys come from The Odds API's bookmaker list. Up to 10 enabled bookmakers cost the same; the 11th doubles odds credits.

**Change a contract** (`oddsmith_tools.json`, `contracts/`): edit on `main`, validate, commit, tell the affected lanes to rebase.

## Still open

From `SPEC.md` and later discussion; settle them here and record the result in `DECISIONS.md`:

- **Before the beta:** domain and magic-link email sender (Supabase's built-in email sends only a few per hour); how long chat messages are kept.
- **From the spec:** player props source; value model now or after the beta; beta size (about 20 or about 100).
- **To do:** data licence checks for API-Football and The Odds API; Supabase Pro on the hosted project before beta day; Sentry DSN by day 8.

## Log

Newest first. One line per lead-lane session: date, what changed, commit.

- **2026-10-08 (later):** Merged orchestrator (odds tools, Claude loop, `answer()`), backend (Sentry, alerts, runbook) and web (all screens and routes); fixed backend wiring tests for the real orchestrator; installed the Railway CLI. Deploy option 1 chosen.
- **2026-10-08:** Merged ingestion's Sentry, matchweek check, Railway cron image and `DEPLOY.md`. Decision 9: `DAILY_TOKEN_BUDGET=4000000`, `VALUE_EDGE_THRESHOLD=0.05`. Merged ingestion's lean odds cadence and its default fix (`dff1a6a`); decision 8 (Odds API free tier, `ODDS_CADENCE`); `.env.example` updated.
- **2026-10-07 (end of day):** Merged ingestion (availability, odds, BTTS, cron tick), orchestrator (tool layer), backend (contract tests, Docker/Railway) and web (API client); rebuilt `api/uv.lock`; added missing env vars and `db/test-db.sh lead`; rebased all lanes.
- **2026-10-07 (later):** Merged web (scaffold + generated types). Merged ingestion (`b731666`) and backend (`f481f0f`); rebased ingestion, backend and web. Fixed on `main`: OpenAPI discriminator mappings, `.gitignore`, API-Football Pro decision + season env vars.
- **2026-10-07:** Applied decisions: everything on Supabase, profiles table, Sonnet 5.5/Opus 5.5, voyage-4, news deferred, 8 bookmakers (`c3eddcb`). Ran `supabase init`, local stack up, `.env` points at local and hosted values are in `.env.production` (`92c3984`).
- **2026-10-06:** Repo scaffold; Phase 0 contracts (schema, 11 tool schemas, OpenAPI + SSE, lane CLAUDE.md files); four lane worktrees (`46af2c0`).
