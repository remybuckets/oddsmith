#!/usr/bin/env bash
# Create (or recreate) a lane's test database and apply every migration to it.
# Usage: db/test-db.sh <ingestion|orchestrator|backend>
# Targets the local Supabase Postgres by default; override with ADMIN_DATABASE_URL.
# Prints the test database URL on success.
set -euo pipefail

LANE="${1:?usage: db/test-db.sh <ingestion|orchestrator|backend>}"
case "$LANE" in
  ingestion|orchestrator|backend) ;;
  *) echo "unknown lane: $LANE" >&2; exit 1 ;;
esac

ADMIN_URL="${ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"
DB="oddsmith_test_${LANE}"
TEST_URL="${ADMIN_URL%/*}/${DB}"
MIGRATIONS_DIR="$(cd "$(dirname "$0")/.." && pwd)/supabase/migrations"
export PGOPTIONS="-c client_min_messages=warning"

psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q \
  -c "DROP DATABASE IF EXISTS ${DB} WITH (FORCE)" \
  -c "CREATE DATABASE ${DB}"

# Stand-in for Supabase's auth schema; real Supabase databases already have it.
psql "$TEST_URL" -v ON_ERROR_STOP=1 -q \
  -c "CREATE SCHEMA auth" \
  -c "CREATE TABLE auth.users (id uuid PRIMARY KEY)"

for file in "$MIGRATIONS_DIR"/*.sql; do
  psql "$TEST_URL" -v ON_ERROR_STOP=1 -q --single-transaction -f "$file"
done

echo "$TEST_URL"
