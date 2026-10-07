# Ingestion lane

You own `ingestion/` only. Read `SPEC.md` ("Data sources", "Ingestion jobs"), `DECISIONS.md` and `supabase/migrations/` first.

## Build order (SPEC build plan, days 1–3)

1. Project setup: `uv` project in `ingestion/`, Python 3.12, provider clients with retries and quota logging.
2. **Record real provider responses first** into `ingestion/tests/fixtures/` (one per endpoint used). Other lanes depend on these; tests replay them, never hit the network.
3. Day-1 checks: does API-Football return xG per player and per team for the Premier League? Injuries? Report findings to the user.
4. `seed_reference` (teams, squads, `entity_aliases` incl. nicknames like "Spurs", "Villa", "KDB").
5. `backfill_season` (2026/27 MW1–5 + 2025/26), `sync_fixtures`, `sync_results`.
6. `sync_availability`, `sync_odds`, `job_runs`. For odds, pass `bookmakers=<enabled keys from the bookmakers table>` instead of `regions=uk`, so adding a bookmaker is just a new row. `ingest_news` is deferred until after the beta.

## Rules

- Every job is idempotent: upsert on `provider_id`; `odds_snapshots` is append-only (`ON CONFLICT DO NOTHING`).
- Every job writes a `job_runs` row (running → success/failed with row count and error).
- Map provider values to the schema's enums (status, position, market, selection) in one place.
- `entity_aliases.alias_search` = lowercased, accent-stripped alias.
- Watch quota: API-Football is on Pro (7,500 req/day, 300/min; see DECISIONS.md #7); The Odds API cost = markets × regions per call. Log remaining quota from response headers.
- News: store headline, summary and link only — never full article text.
- Tests use the database printed by `db/test-db.sh ingestion` and recorded fixtures.
- Do not touch `db/`, `supabase/`, `contracts/`, `api/`, `web/`. Need a schema change? Stop and tell the user.
