# Handoff

Where the project stands and how to pick it up. **Update the "Status" and "Log" sections at the end of every lead-lane session.** Rules live in `CLAUDE.md`, scope in `SPEC.md`, settled choices in `DECISIONS.md`. This file is for what those don't cover.

## Status (as of 2026-10-07, build day 2)

- **Phase 0 (contracts) is done.** Schema, tool schemas, API contract and lane rules are on `main`.
- **All four lanes have started. Nothing is merged to `main` yet.**

| Lane | State | Done | Left |
| --- | --- | --- | --- |
| Ingestion | 3 commits (`031c91f`) | uv project; API-Football + Odds API clients (retries, quota guard); recorded fixtures in `ingestion/tests/fixtures/`; `seed_reference`, `sync_fixtures`, `sync_results` (batched `/fixtures?ids=` on Pro), `backfill_season`; `job_runs` wrapper; CLI | `sync_availability`, `sync_odds`; scheduling |
| Backend | 1 commit (`47cb699`) | Everything in `contracts/openapi.yaml`: JWT via JWKS, `/me`, onboarding, break, account delete, conversations, SSE chat, gates (age → break → IP → daily 15 → token budget), feedback, `/health`, `/fixtures/next`. 107 tests, 99% coverage | Uses a **fake** `orchestrator.answer()` until the orchestrator lane merges |
| Orchestrator | **Uncommitted** work in progress | Contract loader + validation, result envelope, 7 stats tools (`resolve_entity`, player/team stats, H2H, fixtures, league table, availability) with tests | `get_odds`, `get_odds_movement`, `compare_to_market`; Claude tool-use loop; system prompt; `answer()` |
| Web | 1 commit (`72c4922`) + uncommitted `web/src/lib/api/schema.d.ts` | Next.js 16 + Tailwind 4 scaffold, Vitest, Playwright (mobile + desktop), `gen:api` script | All of the UI |

- **Local stack is running:** Supabase (Postgres 17 + Auth) with the migration applied.
- **API-Football is on Pro since 2026-10-07** (any season, `ids` batching). The season comes from `API_FOOTBALL_SEASON`.

**Fixed on `main` (2026-10-07):** OpenAPI discriminator `mapping`s (web can now commit `gen:api` output); `.gitignore` covers Python/Node artefacts; API-Football Pro recorded as decision 7; `API_FOOTBALL_SEASON=2026` and `API_FOOTBALL_MIN_INTERVAL=0.2` in `.env.example` and `.env`.

**Still needs the lead lane:**

1. **Rebase all four lanes on `main`** to pick up the fixes. Web then re-runs `gen:api` and commits `schema.d.ts`.
2. **`api/pyproject.toml` and `api/uv.lock` belong to two lanes.** Backend committed its dependencies; orchestrator has uncommitted additions (`anthropic`, `jsonschema`, pytest/ruff dev group). Merge backend first, then orchestrator rebases, keeps both dependency lists and re-runs `uv lock`.
3. **Ask the orchestrator lane to commit** its work (after rebasing, so the new `.gitignore` keeps `__pycache__/` and `.coverage` out).
4. **Merge ingestion and backend** once their tests pass.

**Next:** items 1–4, then orchestrator finishes the odds tools and the `answer()` loop so backend can drop the fake.

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
- **A cost hook** reports session spend. When it says critical, tell the user before continuing.

## Lead-lane routines

**Merge a lane:**
```bash
git -C ../oddsmith-<lane> log --oneline main..HEAD   # what's new
git merge --no-ff lane/<lane>                          # from ~/Desktop/oddsmith on main
# run that lane's tests, then bring the other lanes up to date:
for l in ingestion orchestrator backend web; do git -C ../oddsmith-$l rebase main; done
```
Merge a lane only when its tests pass. If a rebase conflicts in `uv.lock`, re-run `uv lock`.

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

- **2026-10-07 (later):** Status review: all four lanes under way, none merged. Fixed on `main`: OpenAPI discriminator mappings, `.gitignore`, API-Football Pro decision + season env vars.
- **2026-10-07:** Applied decisions: everything on Supabase, profiles table, Sonnet 5.5/Opus 5.5, voyage-4, news deferred, 8 bookmakers (`c3eddcb`). Ran `supabase init`, local stack up, `.env` points at local and hosted values are in `.env.production` (`92c3984`).
- **2026-10-06:** Repo scaffold; Phase 0 contracts (schema, 11 tool schemas, OpenAPI + SSE, lane CLAUDE.md files); four lane worktrees (`46af2c0`).
