#!/usr/bin/env bash
# Apply pending migrations in db/migrations/ to $DATABASE_URL, each in its own transaction.
# Usage: DATABASE_URL=postgresql://... db/migrate.sh
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is not set}"
export PGOPTIONS="-c client_min_messages=warning"
MIGRATIONS_DIR="$(cd "$(dirname "$0")" && pwd)/migrations"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c \
  "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"

for file in "$MIGRATIONS_DIR"/*.sql; do
  version="$(basename "$file" .sql)"
  if [ "$(psql "$DATABASE_URL" -tAc "SELECT 1 FROM schema_migrations WHERE version = '$version'")" = "1" ]; then
    continue
  fi
  echo "Applying $version"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q --single-transaction \
    -f "$file" \
    -c "INSERT INTO schema_migrations (version) VALUES ('$version')"
done

echo "Migrations up to date"
