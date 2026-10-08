# Deploying the API to Railway

Runbook for the FastAPI service (`api/`). The API serves the web app, runs the stale-job
watcher and reports to Sentry. Ingestion runs as a separate Railway cron; see `ingestion/`.

**Status: not deployed yet.** Don't deploy until the lead lane gives the go-ahead.

## 1. Before the first deploy

| Need | Where it comes from |
| --- | --- |
| Hosted Supabase project (London), migrations applied | Lead lane: `supabase link`, then `supabase db push` |
| Supabase on Pro | The free tier pauses idle projects (DECISIONS 1) |
| Sentry project (platform: Python → FastAPI) | sentry.io → Projects → Create. Copy the DSN |
| Web app URL | Vercel, for `CORS_ALLOWED_ORIGINS` |
| `orchestrator.answer()` merged | Until then the API serves **canned answers**; the startup log says `using the FAKE orchestrator` |

## 2. Railway services

One Railway project with three services: **api** (this one), **ingestion** (cron) and **Redis**.

1. **Redis:** New → Database → Redis. Railway exposes `REDIS_URL` on it.
2. **api:** New → GitHub repo → this repo, then in the service's Settings:
   - **Root directory:** leave empty (repo root). The image needs `oddsmith_tools.json` from the root.
   - **Config file path:** `api/railway.json`. It sets the Dockerfile build, the `/health`
     healthcheck, restart on failure and watch paths (`api/**`, `oddsmith_tools.json`).
   - **Networking:** Generate Domain. Note the URL for the web app's `NEXT_PUBLIC_API_URL`.
   - **Region:** EU West, next to Supabase London.
3. Leave replicas at **1** for the beta. More replicas work (counters and alerts live in Redis),
   but each one opens its own database pool of up to 10 connections.

## 3. Variables (api service)

Set these in the api service's Variables. Never commit them; hosted values are in the main
repo's `.env.production`.

| Variable | Value | Required |
| --- | --- | --- |
| `DATABASE_URL` | Supabase **session pooler** URL: `postgresql://postgres.<ref>:<password>@aws-0-eu-west-2.pooler.supabase.com:5432/postgres`. Port **5432** (session). Never 6543 (transaction): it breaks asyncpg | yes |
| `SUPABASE_URL` | `https://<ref>.supabase.co`. Must match the token issuer exactly | yes |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Settings → API keys. The app won't start without it | yes |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` (Railway reference variable) | yes |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL_FAST`, `CLAUDE_MODEL_STRONG` | Read by the orchestrator once it merges | yes |
| `CORS_ALLOWED_ORIGINS` | The Vercel URL, e.g. `https://oddsmith.vercel.app`. Comma-separate several | yes |
| `FORWARDED_ALLOW_IPS` | `*`. Railway's proxy has no fixed IP. **Check this after the first deploy** (step 5) | yes |
| `SENTRY_DSN` | From the Sentry project. Without it, errors are only logged and the startup log warns | yes |
| `DAILY_TOKEN_BUDGET` | `4000000` (DECISIONS 9). Empty means **no budget**, and the startup log warns | yes |
| `DAILY_QUESTION_LIMIT`, `PER_IP_REQUESTS_PER_MINUTE` | Defaults 15 and 10 | no |
| `NEWS_ENABLED` | `false` | no |
| `SENTRY_ENVIRONMENT` | Defaults to Railway's environment name (`production`) | no |

Railway sets `PORT`, `RAILWAY_ENVIRONMENT_NAME` and `RAILWAY_GIT_COMMIT_SHA` itself. The last
two become Sentry's environment and release.

## 4. Sentry alerts

The API sends Sentry:
- **Errors:** every unhandled exception, failed answer and failed account deletion, with the
  user id only. Request bodies (questions), tokens, cookies, emails and IPs are stripped
  before sending.
- **Stale-job warnings:** every 15 minutes the API checks ingestion with the same rules as
  `/health`. When a job goes stale it sends one warning per job, tagged `alert:job_stale` and
  `job:<name>`, and repeats it every 6h while the job stays stale. A recovered job is logged.
- **Traces:** 10% of requests, for time-to-first-token (target under 4s).

Create these alert rules (Alerts → Create Alert → Issues), filtered to environment `production`:

| Rule | Conditions | Action |
| --- | --- | --- |
| New error | A new issue is created; level is `error` or above | Email (or Slack) |
| Stale ingestion job | An event is seen; the event's tags match `alert` equals `job_stale` | Email, at most once every 6h per issue |
| Error spike | Number of events in an issue is more than 20 in 1 hour | Email |

Optional: a Sentry Uptime monitor (or any uptime checker) on `GET /health` every 5 minutes. It
catches the whole API being down, which the in-app watcher can't report.

When a job goes stale:

| Stale job | Stale when | First check |
| --- | --- | --- |
| `sync_fixtures` | over 30h since last success | ingestion cron logs; API-Football quota |
| `sync_results` | a match that kicked off over 4h ago isn't marked finished | ingestion cron logs; API-Football status for that fixture |
| `sync_availability` | over 13h | ingestion cron logs |
| `sync_odds` | over 26h (lean cadence, DECISIONS 8) | The Odds API credits left (500/month free) |
| `seed_reference` | over 8 days | ingestion cron logs |
| `backfill_season`, `sync_btts` | never succeeded | run the job by hand from `ingestion/` |

`job_runs.error` in Supabase holds each failed run's error message.

## 5. First deploy

1. Check main is green: `cd api && uv run pytest -q`.
2. Deploy the api service from `main`. Railway builds `api/Dockerfile` and waits for `/health`
   to return 200. It returns 200 even when the status is `degraded`, so a stale job doesn't
   block a deploy.
3. Check the deploy logs for the startup warnings. In production none should appear:
   `SENTRY_DSN is not set`, `DAILY_TOKEN_BUDGET is not set`, `using the FAKE orchestrator`.
4. Run the smoke test from your machine. It creates a throwaway user, asks one question, then
   deletes the user:
   ```bash
   cd api
   API_URL=https://<api-domain> SUPABASE_URL=https://<ref>.supabase.co \
   SUPABASE_SERVICE_ROLE_KEY=... SUPABASE_ANON_KEY=... uv run python scripts/smoke.py
   ```
5. **Check the client IP is real and can't be spoofed.** Send
   `curl -H 'X-Forwarded-For: 1.2.3.4' https://<api-domain>/health` and look at the uvicorn
   access log line.
   - **Your real IP:** good.
   - **`1.2.3.4`:** clients can pick their IP and dodge the per-IP limit. Tell the backend lane;
     the fix is to read the right-most address Railway appends.
   - **Some other address that isn't yours:** it's Railway's proxy, so `FORWARDED_ALLOW_IPS`
     isn't taking effect; every user shares one 10/min bucket.
6. Check Sentry receives events: Sentry → the project → Issues, filtered to `production`. Don't
   add a debug route. Point the web app at the API and sign in once; the first stale-job
   warning, if any, arrives within 15 minutes.
7. Set `NEXT_PUBLIC_API_URL` on Vercel to the API domain. Then check `CORS_ALLOWED_ORIGINS`
   matches the Vercel URL exactly: scheme, no trailing slash.

## 6. Day-to-day

- **Deploys:** every push to `main` that touches `api/**` or `oddsmith_tools.json` redeploys.
  Railway swaps traffic only once the new deploy passes its healthcheck. An answer that is
  still streaming when the old container stops ends without `message_end`, and the question
  stays used.
- **Rollback:** Railway → api → Deployments → pick the last good one → Redeploy. Migrations
  aren't rolled back by this. If a migration caused it, the lead lane adds a new migration.
- **Logs:** Railway → api → Logs. Lines are `time LEVEL logger: message`.
- **Usage and cost:** `usage_daily` in Supabase holds per-user questions and tokens. The global
  daily token counter is the Redis key `tokens:<YYYY-MM-DD>` (UK date).
- **Budget hit:** chat returns `budget_exhausted` ("back tomorrow") until UK midnight. To raise
  the budget mid-day, change `DAILY_TOKEN_BUDGET` and redeploy (the counter in Redis is kept).
- **Redis restart:** today's question and token counters reset, so users get a fresh 15 for
  the rest of the day. Rate-limit and alert keys rebuild themselves.
