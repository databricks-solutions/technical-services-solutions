#!/usr/bin/env bash
# Create the `orderflow` database in the Lakebase project and apply schema + seed data.
# Usage: PROFILE=<cli-profile> ./scripts/init_db.sh
set -euo pipefail

PROFILE="${PROFILE:?set PROFILE to your Databricks CLI profile}"
PROJECT="${LAKEBASE_PROJECT:-orderflow-db}"
BRANCH="${LAKEBASE_BRANCH:-production}"
ENDPOINT="${LAKEBASE_ENDPOINT:-primary}"
DBNAME="${LAKEBASE_DB:-orderflow}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# psql from Homebrew keg is often not on PATH.
if ! command -v psql >/dev/null 2>&1; then
  export PATH="/opt/homebrew/opt/libpq/bin:/opt/homebrew/opt/postgresql@16/bin:$PATH"
fi

echo ">> Resolving connection details (profile=$PROFILE)…"
HOST=$(databricks postgres list-endpoints "projects/$PROJECT/branches/$BRANCH" -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['status']['hosts']['host'])")
TOKEN=$(databricks postgres generate-database-credential "projects/$PROJECT/branches/$BRANCH/endpoints/$ENDPOINT" -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
EMAIL=$(databricks current-user me -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['userName'])")

echo ">> Host: $HOST"
echo ">> Creating database '$DBNAME' if absent…"
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=postgres user=$EMAIL sslmode=require" \
  -tc "SELECT 1 FROM pg_database WHERE datname='$DBNAME'" | grep -q 1 \
  || PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=postgres user=$EMAIL sslmode=require" -c "CREATE DATABASE $DBNAME;"

echo ">> Applying schema…"
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=$DBNAME user=$EMAIL sslmode=require" -v ON_ERROR_STOP=1 -f "$HERE/schema.sql"

echo ">> Seeding data…"
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=$DBNAME user=$EMAIL sslmode=require" -v ON_ERROR_STOP=1 -f "$HERE/seed.sql"

echo ">> Done. Row counts:"
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=$DBNAME user=$EMAIL sslmode=require" -c \
  "SELECT 'products' t, count(*) FROM products UNION ALL SELECT 'customers', count(*) FROM customers UNION ALL SELECT 'orders', count(*) FROM orders UNION ALL SELECT 'order_items', count(*) FROM order_items;"
