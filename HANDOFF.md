# Handoff

Where the project stands and how to pick it up. **Update the "Status" and "Log" sections at the end of every lead-lane session.** Rules live in `CLAUDE.md`, scope in `SPEC.md`, settled choices in `DECISIONS.md`. This file is for what those don't cover.

## Status (as of 2026-10-07, build day 2)

- **Phase 0 (contracts) is done.** Schema, tool schemas, API contract and lane rules are on `main`.
- **No lane has started coding yet.** All four lane branches sit at the same commit as `main`.
- **Local stack is running:** Supabase (Postgres 17 + Auth) with the migration applied.
- **Next:** start the four lanes (below). Ingestion is on the critical path: other lanes need its recorded provider responses and seeded data.

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

- **2026-10-07:** Applied decisions: everything on Supabase, profiles table, Sonnet 5.5/Opus 5.5, voyage-4, news deferred, 8 bookmakers (`c3eddcb`). Ran `supabase init`, local stack up, `.env` points at local and hosted values are in `.env.production` (`92c3984`).
- **2026-10-06:** Repo scaffold; Phase 0 contracts (schema, 11 tool schemas, OpenAPI + SSE, lane CLAUDE.md files); four lane worktrees (`46af2c0`).
