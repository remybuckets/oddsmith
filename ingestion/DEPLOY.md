# Ingestion: deploy and matchweek runbook

The worker is one command, `python -m oddsmith_ingestion.cli tick`. Each run checks `job_runs` and the fixture list, runs whatever is due, and then exits. A Railway cron starts it every 30 minutes. Cadences are in `src/oddsmith_ingestion/schedule.py`.

**Status: not deployed yet.** The image builds and runs locally: `docker build -f ingestion/Dockerfile .` from the repo root.

## 1. Before the first deploy

1. **Hosted database URL.** Use Supabase's **session pooler** or the direct connection, and append `?sslmode=require`. Never use the transaction pooler (port 6543), because it breaks asyncpg prepared statements.
2. **Load the hosted database once, from a laptop.** Run these from `ingestion/` with the hosted URL. Together they cost about 110 API-Football requests.
   ```bash
   export DATABASE_URL='postgresql://...pooler.supabase.com:5432/postgres?sslmode=require'
   uv run python -m oddsmith_ingestion.cli seed_reference
   uv run python -m oddsmith_ingestion.cli backfill_season --season 2025   # 2025/26, head-to-heads
   uv run python -m oddsmith_ingestion.cli backfill_season                 # 2026/27 so far
   uv run python -m oddsmith_ingestion.cli sync_availability
   uv run python -m oddsmith_ingestion.cli sync_odds                       # 2 Odds API credits
   uv run python -m oddsmith_ingestion.cli check                           # expect 0 problems
   ```

## 2. Railway service (cron)

1. In the existing Railway project, add a service from the GitHub repo. Leave the root directory as the repo root, because the Dockerfile copies `ingestion/` from there.
2. Settings → Config-as-code → path `ingestion/railway.json`. That file sets:
   - the Dockerfile build;
   - `cronSchedule: */30 * * * *`, which Railway reads as UTC (the jobs handle UK times themselves);
   - `restartPolicyType: NEVER`;
   - rebuilds only when files under `ingestion/` change.
3. Variables (Service → Variables). Paste bare values only: Railway does not strip `# comments`, so `2026   # season` would break the integer setting.

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | hosted session-pooler URL with `?sslmode=require` |
   | `API_FOOTBALL_KEY` | from `.env.production` |
   | `ODDS_API_KEY` | from `.env.production` |
   | `API_FOOTBALL_SEASON` | `2026` |
   | `API_FOOTBALL_MIN_INTERVAL` | `0.2` (Pro plan) |
   | `ODDS_CADENCE` | `lean` (free Odds API tier; `full` after buying the 20K plan) |

4. Deploy. Nothing runs until the next `:00` or `:30`.

## 3. Verify after deploy

- **Railway logs** for the cron run should show `tick: due [...]`, a `job ... succeeded` line per job, and remaining quota for both providers. Exit code 1 means a job failed. The error is in the log and in `job_runs.error`.
- **Supabase SQL:** `SELECT name, status, rows, started_at, error FROM job_runs ORDER BY id DESC LIMIT 20;`
- **From a laptop:** `DATABASE_URL=<hosted> uv run python -m oddsmith_ingestion.cli check`.
- **Backend:** `GET /health` lists the last successful run per job.

## 4. Budgets

| Provider | Plan | Expected use |
| --- | --- | --- |
| API-Football | Pro, 7,500/day, renews 2026-11-07 | a few hundred a day. Busiest is matchday: `sync_availability` about 10 an hour, results 1 per 20 matches |
| The Odds API | free, 500 credits a month | about 300 a month on `lean`. `sync_odds` is 2 credits; `sync_btts` is 1 per match on matchday mornings |

When fewer than `ODDS_API_QUOTA_RESERVE` credits are left (default 50), the clients stop calling and the job fails with `QuotaExhausted`. The same applies to API-Football with `API_FOOTBALL_QUOTA_RESERVE`, default 10.

**To pause:** remove the cron schedule in the service settings, or remove the service. Overlapping runs are already prevented by a Postgres advisory lock.

**Not wired yet:** Sentry for the worker (SPEC: day 8). Until then, failures show only in Railway logs and `job_runs`.

## 5. Matchweek runbook (until the cron is live)

Run the loop from `ingestion/` on a machine that stays awake. Start it Saturday morning and leave it running until the last match ends and its results are in.

```bash
while true; do
  uv run python -m oddsmith_ingestion.cli tick
  uv run python -m oddsmith_ingestion.cli check
  sleep 1800
done
```

Matchweek 6 timeline (UK time): Arsenal v Leeds is first, Saturday 12:30; Coventry v Newcastle is last, Monday 20:00.

| When | Expect |
| --- | --- |
| From 08:00 on each matchday | odds every 2h until 20:00; BTTS once (the first tick after 08:00); availability hourly |
| Kick-off + 2h | `sync_results` starts fetching that match every 30 min |
| Kick-off + 3h | `check` reports `result_overdue` if the match still isn't finished and scored |

What each `check` problem means:

| Problem | Likely cause | Action |
| --- | --- | --- |
| `odds_missing` / `odds_stale` | `sync_odds` not run, or failed | read `job_runs.error`; run `cli sync_odds` by hand (2 credits) |
| `odds_incomplete` | bookmakers not pricing yet, or an Odds API team name not matched (a `no fixture` warning in the log) | if names: add the Odds API name to `reference_data.py` and run `seed_reference` |
| `availability_stale` | `sync_availability` failing | read `job_runs.error`; run `cli sync_availability` |
| `result_overdue` | match delayed or abandoned, or provider late | after kick-off + 4h, check the match status by hand; abandoned matches map to `cancelled` |
| `team_stats_missing` / `player_stats_thin` | provider published the score before the stats | the next ticks retry automatically, for up to 14 days |
| `score_mismatch` | provider corrected the score after the stats | run `cli sync_results` again; both are upserted |
| `xg_missing` | provider hasn't filled in xG yet | it usually arrives later; `sync_results` re-fetches a match until its xG is in, for up to 14 days |
| `job_failed` | see its error | `QuotaExhausted`: wait for the reset or raise the plan. Anything else: fix, then re-run that job |
