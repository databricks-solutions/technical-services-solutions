#!/usr/bin/env bash
# Grant a Databricks App's service principal access to the OrderFlow Lakebase DB.
#
# 1. Creates a Postgres role for the SP (OAuth-backed).
# 2. Grants it privileges on the `orderflow` database + public schema.
#
# Usage: PROFILE=<profile> APP_SP_CLIENT_ID=<uuid> ./scripts/grant_app_role.sh
set -euo pipefail

PROFILE="${PROFILE:?set PROFILE to your Databricks CLI profile}"
PROJECT="${LAKEBASE_PROJECT:-orderflow-db}"
BRANCH="${LAKEBASE_BRANCH:-production}"
ENDPOINT="${LAKEBASE_ENDPOINT:-primary}"
DBNAME="${LAKEBASE_DB:-orderflow}"
SP="${APP_SP_CLIENT_ID:?set APP_SP_CLIENT_ID to the app service principal client id}"
# role_id is a resource identifier and must start with a letter; the SP client id
# (used as the actual Postgres username) is stored in spec.postgres_role.
ROLE_ID="${APP_ROLE_ID:-app-orderflow}"

if ! command -v psql >/dev/null 2>&1; then
  export PATH="/opt/homebrew/opt/libpq/bin:/opt/homebrew/opt/postgresql@16/bin:$PATH"
fi

echo ">> Creating Postgres role for SP $SP …"
databricks postgres create-role "projects/$PROJECT/branches/$BRANCH" \
  --role-id "$ROLE_ID" \
  --json "{\"spec\": {\"identity_type\": \"SERVICE_PRINCIPAL\", \"postgres_role\": \"$SP\", \"auth_method\": \"LAKEBASE_OAUTH_V1\"}}" \
  -p "$PROFILE" 2>&1 | tail -5 || echo "(role may already exist)"

echo ">> Granting privileges on database '$DBNAME' …"
HOST=$(databricks postgres list-endpoints "projects/$PROJECT/branches/$BRANCH" -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['status']['hosts']['host'])")
TOKEN=$(databricks postgres generate-database-credential "projects/$PROJECT/branches/$BRANCH/endpoints/$ENDPOINT" -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
EMAIL=$(databricks current-user me -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['userName'])")

PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=$DBNAME user=$EMAIL sslmode=require" -v ON_ERROR_STOP=1 <<SQL
GRANT USAGE ON SCHEMA public TO "$SP";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "$SP";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "$SP";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "$SP";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "$SP";
SQL

echo ">> Done. App SP $SP can now read/write the OrderFlow tables."
