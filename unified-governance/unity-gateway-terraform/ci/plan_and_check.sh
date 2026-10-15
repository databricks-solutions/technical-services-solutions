#!/bin/bash
# CI gate for the grants and budgets projects.
#   ci/plan_and_check.sh <tf-dir>                              plan + destroy guard
#   ci/plan_and_check.sh <tf-dir> --snapshot snap.json         + first-apply check (grants only)
#   ci/plan_and_check.sh <tf-dir> [--snapshot snap.json] --apply   + apply the exact saved plan
set -euo pipefail
DIR="$1"; shift
SNAPSHOT=""; APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --apply)    APPLY=1; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
HERE="$(cd "$(dirname "$0")/.." && pwd)"

terraform -chdir="$DIR" plan -input=false -out=tf.plan
terraform -chdir="$DIR" show -json tf.plan > "$DIR/plan.json"

# 1. Never delete or replace a grant or budget resource from CI: a delete revokes access or drops a cap.
python3 - "$DIR/plan.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
watched = ("databricks_grants", "databricks_grant", "databricks_budget")
bad = [rc["address"] for rc in plan.get("resource_changes", [])
       if rc["type"] in watched and "delete" in rc["change"]["actions"]]
if bad:
    print("Plan deletes protected resources:"); [print("  -", a) for a in bad]; sys.exit(1)
print("OK: no grant or budget resource is deleted or replaced.")
PY

# 2. First apply only: the planned grants must equal today's grants.
if [ -n "$SNAPSHOT" ]; then
  python3 "$HERE/scripts/check_plan_vs_snapshot.py" --plan "$DIR/plan.json" --snapshot "$SNAPSHOT" \
    --break-glass "${BREAK_GLASS_GROUP:-platform-admins}"
fi

if [ "$APPLY" = 1 ]; then
  terraform -chdir="$DIR" apply -input=false tf.plan
fi
