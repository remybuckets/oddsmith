# Handoff

Where the project stands and how to pick it up. **Update the "Status" and "Log" sections at the end of every lead-lane session.** Rules live in `CLAUDE.md`, scope in `SPEC.md`, settled choices in `DECISIONS.md`. This file is for what those don't cover.

## Status (as of 2026-10-10, build day 5)

**Everything is deployed: hosted database, ingestion cron, API and web app (see "Production" below). Sign-in and 18+ onboarding work on the live site (user, 2026-10-10 evening); the user asked a question through the live site and got an answer.** All four lanes' work is merged to `main` (`c3537db`) and pushed to GitHub. On `main`: api 314 tests, ingestion 180 (not re-run today), web 172 + typecheck + lint + `next build` (9 routes).

| Lane | On `main` | Pick up next |
| --- | --- | --- |
| **Ingestion** | Provider clients (retries, quota guard); all beta jobs with a `lean` odds cadence (decision 8); `cli tick` (30-minute cron, advisory lock); `cli check` (matchweek health report); Sentry with provider keys scrubbed; `ingestion/Dockerfile` + `railway.json`; `ingestion/DEPLOY.md`. MW6 live check 2026-10-08: 0 problems | Cron is live on Railway (first run 2026-10-10 13:00 UK). Watch MW6 through Mon 12 Oct with `cli check`. **Update `ingestion/DEPLOY.md`:** Railway's config-as-code is deprecated, so `railway.json` is not read by new services; the settings were entered by hand (see "Production") |
| **Orchestrator** | All 10 beta tools incl. `get_odds`, `get_odds_movement`, `compare_to_market`; Claude tool-use loop (max 8 tool calls, Opus for value questions, prompt caching); system prompt in its own file; stat/odds/value cards validated against the contract; `answer()` exported and used by backend | **Day 7 eval:** a 50-question eval set run against real data; fix every wrong figure; guardrail tests (no "locks", estimates labelled, under-18 / break flows). Measure real cost per answer to re-set `DAILY_TOKEN_BUDGET` |
| **Backend** | Full contract; real orchestrator; Sentry; stale-job alerts; `api/scripts/smoke.py`; `api/DEPLOY.md`; Dockerfile + `railway.json` | API is live on Railway; smoke script passed 2026-10-10; client-IP check passed (forged `X-Forwarded-For` ignored). **Update `api/DEPLOY.md`:** same config-as-code change; `SUPABASE_SERVICE_ROLE_KEY` is now a new-style `sb_secret_` key; `VALUE_EDGE_THRESHOLD` and `PORT=8000` are set but not in the runbook's table; Sentry uptime monitors can't be created on `*.railway.app` (Sentry's per-domain limit), so that needs a custom domain or another checker |
| **Web** | Every screen: landing, magic-link sign-in + callback, 18+ onboarding, chat (fixture strip, streaming answers, stat/odds/value cards, feedback, chat list), settings (usage, take-a-break, delete account), draft terms + privacy; copy test blocks "lock/banker/guaranteed/sure thing" | Web is live on Vercel. **Sign-in:** the "couldn't send the link" message says "wait a minute" but Supabase's built-in sender blocks for up to an hour; consider a six-digit code or a confirm button instead of a bare magic link (Outlook/Hotmail scanners can use links up; not confirmed as a cause here). End-to-end Playwright run against the local stack still to do; terms and privacy are **drafts pending review** |

**Production (deployed 2026-10-10):**

| Piece | Where | Notes |
| --- | --- | --- |
| Code | GitHub `remybuckets/oddsmith` (private), branch `main` | Railway and Vercel both deploy from it on push |
| Database | Supabase project `oddsmith` (eu-west-1), CLI linked | `20261006000000_init.sql` applied; first load done (20 teams, 624 players, seasons 2025 and 2026, availability, odds); `cli check`: 0 problems. Schema pushes: the user runs `! supabase db push --linked` (Claude's auto mode blocks it) |
| Ingestion cron | Railway project `oddsmith`, service `ingestion` | Dockerfile `ingestion/Dockerfile`, watch `ingestion/**`, cron `*/30 * * * *`, restart never; 7 variables |
| API | Railway service `api`, https://api-production-82070.up.railway.app | Dockerfile `api/Dockerfile`, watch `api/**` + `oddsmith_tools.json`, healthcheck `/health`, port 8000; 14 variables; Redis is the Railway service `Redis` |
| Web | Vercel, https://oddsmith-82md.vercel.app | Root `web`, install command `npx npm@11 install`, three `NEXT_PUBLIC_*` variables. `NEXT_PUBLIC_API_URL` is baked in at build time: change it, then redeploy |
| Sentry | Org `oddsmith` (EU), projects `oddsmith-api` and `oddsmith-ingestion` | Each Railway service has its own `SENTRY_DSN`. Alerts (email to team `oddsmith`, environment `production`): "Stale ingestion job" (tag `alert=job_stale`, at most every 6h), "New error in production", "Error spike (over 20 events in 1 hour)". No uptime monitor |

- **Railway variables:** Claude's auto mode blocks writing secrets to Railway. The user runs a script that reads `.env` / `.env.production` and calls `railway variables --set ... --skip-deploys`. `.env.production` now holds the session-pooler `DATABASE_URL` and the `sb_secret_` key; provider and Anthropic keys are only in `.env`.
- **Railway settings are entered in the dashboard.** New services can't use `railway.json` (config-as-code deprecated; existing files stop working 2026-12-01). The `railway.json` files in the repo are not in use.
- **All three Railway services are in US East (`iad`)**, not EU West next to the database. `railway scale <svc> eu-west=1 us-east=0` on 2026-10-10 produced failed deploys with no logs and changed nothing; the user believes region choice needs a higher Railway plan (not confirmed). Revisit before the beta if answers feel slow.
- **Supabase Auth → URL Configuration** must have the Vercel URL as Site URL and `https://oddsmith-82md.vercel.app/**` as a redirect URL, or magic links go to localhost. Set by the user on 2026-10-10 (sign-in now lands on the site).
- **Sign-in email:** Supabase's built-in sender allows 2 emails an hour and blocked testing on 2026-10-10. The user then chose the stopgap domain `odd-smith.co.uk` (`oddsmith.co.uk`, `.com`, `.app` and `.io` are taken by others; `oddsmith.ai` is the intended final domain, to buy later) and was given steps for Resend + Supabase custom SMTP (sender `login@odd-smith.co.uk`). Custom SMTP is set up and working (user, 2026-10-10 evening). Moving to `oddsmith.ai` later means redoing the Resend DNS, the Supabase sender, Site URL and redirect URLs, `CORS_ALLOWED_ORIGINS` and `NEXT_PUBLIC_API_URL`.
- **Hosted `auth.users` has two test users** (the user's Gmail and Hotmail) from 2026-10-10.

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
- **To do:** data licence checks for API-Football and The Odds API; Supabase Pro on the hosted project before beta day.
- **Beta day** has no fixed date: it is whenever the remaining work is done (user, 2026-10-10). Remaining: Playwright run, day-7 eval and guardrail tests, terms/privacy review, licence checks.

## Log

Newest first. One line per lead-lane session: date, what changed, commit.

- **2026-10-10:** First production deploy. Schema pushed and first data load on the hosted DB; GitHub repo (private); Railway project with `ingestion` cron, `api` and `Redis`; web on Vercel; API smoke test passed; merged lane/web's onboarding-gate fix (`c3537db`); three Sentry alerts. Sentry projects created and verified 2026-10-08. Sign-in confirmed on the live site that evening; cron ran all day with 0 failed runs. The user then asked a question through the live site (worked) and set up custom SMTP on `odd-smith.co.uk`. Open: Railway services still in US East.
- **2026-10-08 (later):** Merged orchestrator (odds tools, Claude loop, `answer()`), backend (Sentry, alerts, runbook) and web (all screens and routes); fixed backend wiring tests for the real orchestrator; installed the Railway CLI. Deploy option 1 chosen.
- **2026-10-08:** Merged ingestion's Sentry, matchweek check, Railway cron image and `DEPLOY.md`. Decision 9: `DAILY_TOKEN_BUDGET=4000000`, `VALUE_EDGE_THRESHOLD=0.05`. Merged ingestion's lean odds cadence and its default fix (`dff1a6a`); decision 8 (Odds API free tier, `ODDS_CADENCE`); `.env.example` updated.
- **2026-10-07 (end of day):** Merged ingestion (availability, odds, BTTS, cron tick), orchestrator (tool layer), backend (contract tests, Docker/Railway) and web (API client); rebuilt `api/uv.lock`; added missing env vars and `db/test-db.sh lead`; rebased all lanes.
- **2026-10-07 (later):** Merged web (scaffold + generated types). Merged ingestion (`b731666`) and backend (`f481f0f`); rebased ingestion, backend and web. Fixed on `main`: OpenAPI discriminator mappings, `.gitignore`, API-Football Pro decision + season env vars.
- **2026-10-07:** Applied decisions: everything on Supabase, profiles table, Sonnet 5.5/Opus 5.5, voyage-4, news deferred, 8 bookmakers (`c3eddcb`). Ran `supabase init`, local stack up, `.env` points at local and hosted values are in `.env.production` (`92c3984`).
- **2026-10-06:** Repo scaffold; Phase 0 contracts (schema, 11 tool schemas, OpenAPI + SSE, lane CLAUDE.md files); four lane worktrees (`46af2c0`).
