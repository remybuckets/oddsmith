# Ingestion lane

You own `ingestion/` only. Read `SPEC.md` ("Data sources", "Ingestion jobs") and `db/migrations/0001_init.sql` first.

## Build order (SPEC build plan, days 1–3)

1. Project setup: `uv` project in `ingestion/`, Python 3.12, provider clients with retries and quota logging.
2. **Record real provider responses first** into `ingestion/tests/fixtures/` (one per endpoint used). Other lanes depend on these; tests replay them, never hit the network.
3. Day-1 checks: does API-Football return xG per player and per team for the Premier League? Injuries? Report findings to the user.
4. `seed_reference` (teams, squads, `entity_aliases` incl. nicknames like "Spurs", "Villa", "KDB").
5. `backfill_season` (2026/27 MW1–5 + 2025/26), `sync_fixtures`, `sync_results`.
6. `sync_availability`, `sync_odds`, `ingest_news` (Voyage embeddings, 1024 dims), `job_runs`.

## Rules

- Every job is idempotent: upsert on `provider_id`; `odds_snapshots` is append-only (`ON CONFLICT DO NOTHING`).
- Every job writes a `job_runs` row (running → success/failed with row count and error).
- Map provider values to the schema's enums (status, position, market, selection) in one place.
- `entity_aliases.alias_search` = lowercased, accent-stripped alias.
- Watch quota: API-Football free tier is 100 req/day until the Pro plan is on; The Odds API cost = markets × regions per call. Log remaining quota from response headers.
- News: store headline, summary and link only — never full article text.
- Tests use `oddsmith_test_ingestion` and recorded fixtures.
- Do not touch `db/`, `contracts/`, `api/`, `web/`. Need a schema change? Stop and tell the user.
