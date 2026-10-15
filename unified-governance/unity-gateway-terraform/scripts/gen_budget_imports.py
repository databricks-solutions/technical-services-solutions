#!/usr/bin/env python3
"""Step 5a: write Terraform import blocks for existing budgets (read-only).

  python3 scripts/gen_budget_imports.py --profile <account-profile> --out budgets/imports.tf \
      [--resource-type BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY] [--name-regex '^ai-gateway-']

Then:  terraform -chdir=budgets plan -generate-config-out=budgets_generated.tf
"""
import argparse, json, re, subprocess

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resource-type", default="BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY",
                    help="use ALL to include every budget type")
    ap.add_argument("--name-regex", default=".*")
    args = ap.parse_args()

    out = subprocess.run(["databricks", "account", "budgets", "list", "--profile", args.profile, "-o", "json"],
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    budgets = data if isinstance(data, list) else data.get("budgets", [])
    picked = [b for b in budgets
              if (args.resource_type == "ALL" or b.get("resource_type") == args.resource_type)
              and re.search(args.name_regex, b.get("display_name", ""))]

    used, lines = set(), ["# Generated import blocks. Delete this file after the import is applied.", ""]
    for b in sorted(picked, key=lambda b: b["display_name"]):
        name = re.sub(r"[^a-z0-9_]", "_", b["display_name"].lower()).strip("_") or "budget"
        if name[0].isdigit():
            name = "b_" + name
        base, i = name, 2
        while name in used:
            name, i = f"{base}_{i}", i + 1
        used.add(name)
        lines += ["import {", f"  to = databricks_budget.{name}",
                  f'  id = "{b["account_id"]}|{b["budget_configuration_id"]}"', "}", ""]
    open(args.out, "w").write("\n".join(lines))
    print(f"{len(picked)} of {len(budgets)} budgets -> {args.out}")

if __name__ == "__main__":
    main()
