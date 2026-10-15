#!/usr/bin/env python3
"""Step 3: prove the first plan changes no access. Compares the planned grants with the snapshot.

  terraform -chdir=grants plan -out=tf.plan
  terraform -chdir=grants show -json tf.plan > plan.json
  python3 scripts/check_plan_vs_snapshot.py --plan plan.json --snapshot snapshot/grants.json \
      --break-glass platform-admins

Exit code 0 = planned grants equal the snapshot (only allowed difference: the break-glass group
on models with no grants today). Exit code 1 = any other difference, or any delete.
"""
import argparse, json, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--break-glass", required=True)
    args = ap.parse_args()
    plan, snap = json.load(open(args.plan)), json.load(open(args.snapshot))
    errors, notes, planned = [], [], set()

    for rc in plan.get("resource_changes", []):
        actions = rc["change"]["actions"]
        if "delete" in actions:
            errors.append(f"{rc['address']}: plan deletes it ({actions}); this revokes access")
        after = rc["change"].get("after") or {}
        if rc["type"] == "databricks_grants":
            model = after["model_service"]
            planned.add(model)
            want = {g["principal"]: sorted(g["privileges"]) for g in after.get("grant", [])}
            have = snap["model_services"].get(model)
            if have is None:
                errors.append(f"{model}: not in snapshot")
            elif want == have:
                continue
            elif not have and want == {args.break_glass: ["EXECUTE"]}:
                notes.append(f"{model}: no grants today; break-glass group gets EXECUTE")
            else:
                for p in sorted(set(want) | set(have)):
                    if want.get(p) != have.get(p):
                        errors.append(f"{model}: {p}: today {have.get(p)} -> planned {want.get(p)}")
        elif rc["type"] == "databricks_grant" and after.get("schema") == "system.ai":
            have = snap["schema_system_ai"].get(after["principal"], [])
            if sorted(after["privileges"]) != have:
                errors.append(f"schema system.ai: {after['principal']}: today {have} -> planned {sorted(after['privileges'])}")

    # resource_changes includes no-op resources too, so anything missing here is not in the config.
    unmanaged = sorted(set(snap["model_services"]) - planned)
    if unmanaged:
        errors.append(f"{len(unmanaged)} models in the snapshot are not in the config: {unmanaged}")

    for n in notes:
        print("NOTE ", n)
    for e in errors:
        print("DIFF ", e)
    if errors:
        sys.exit(f"FAILED: {len(errors)} difference(s) between the plan and today's grants.")
    print(f"OK: planned grants equal the snapshot for {len(planned)} models.")

if __name__ == "__main__":
    main()
