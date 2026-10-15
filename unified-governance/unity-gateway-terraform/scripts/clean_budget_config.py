#!/usr/bin/env python3
"""Step 5b: clean the config that `terraform plan -generate-config-out` wrote for budgets.

- removes read-only fields (account_id, budget_configuration_id, create_time, update_time,
  alert_configuration_id, action_configuration_id) and `target = null`
- replaces numeric principal_id values with account-level data source lookups (group, SP or user)

  python3 scripts/clean_budget_config.py --profile <account-profile> \
      --in budgets/budgets_generated.tf --out budgets/budgets.tf
"""
import argparse, json, re, subprocess

def lookup(profile, pid):
    for kind, cmd, attr, field in (
        ("group", "groups", "display_name", "displayName"),
        ("service_principal", "service-principals", "application_id", "applicationId"),
        ("user", "users", "user_name", "userName"),
    ):
        r = subprocess.run(["databricks", "account", cmd, "get", str(pid), "--profile", profile, "-o", "json"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return kind, attr, json.loads(r.stdout)[field]
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    text = open(args.src).read()

    read_only = "account_id|budget_configuration_id|create_time|update_time|alert_configuration_id|action_configuration_id"
    text = re.sub(rf"^\s*({read_only})\s*=.*\n", "", text, flags=re.M)
    text = re.sub(r"^\s*target\s*=\s*null\s*\n", "", text, flags=re.M)

    data_blocks, done = [], {}
    for pid in sorted(set(re.findall(r"principal_id\s*=\s*(\d+)", text))):
        found = lookup(args.profile, pid)
        if not found:
            print(f"WARNING: principal {pid} not found; left as a number")
            continue
        kind, attr, value = found
        ref = f"p_{pid}"
        data_blocks.append(f'data "databricks_{kind}" "{ref}" {{\n  {attr} = "{value}"\n}}\n')
        text = re.sub(rf"(principal_id\s*=\s*){pid}\b", rf"\g<1>data.databricks_{kind}.{ref}.id", text)
        done[pid] = f"{kind} {value}"

    header = "# Cleaned from terraform -generate-config-out. Review before commit.\n\n"
    open(args.out, "w").write(header + "\n".join(data_blocks) + "\n" + text)
    print(f"wrote {args.out}; principals replaced: {len(done)}")

if __name__ == "__main__":
    main()
