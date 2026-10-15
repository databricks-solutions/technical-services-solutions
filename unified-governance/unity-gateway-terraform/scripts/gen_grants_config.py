#!/usr/bin/env python3
"""Step 2: generate grants/access.tf from the snapshot, so the first apply changes nothing.

  python3 scripts/gen_grants_config.py --snapshot snapshot/grants.json --out grants/access.tf
"""
import argparse, json

def hcl_list(xs):
    return "[" + ", ".join(f'"{x}"' for x in xs) + "]"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    snap = json.load(open(args.snapshot))

    lines = [
        f"# Generated from {args.snapshot} (taken {snap['taken_at']}, metastore {snap['metastore_id']}).",
        "# After the first apply, this file is the source of truth: change access with a PR.",
        "locals {",
        "  # Privileges account users keep on the system.ai schema. Must not include EXECUTE.",
        f"  account_users_schema_privileges = {hcl_list(snap['schema_system_ai'].get('account users', []))}",
        "",
        "  # Model -> principal -> privileges. An empty map gets only the break-glass group",
        "  # (databricks_grants needs at least one grant).",
        "  model_grants = {",
    ]
    for model, principals in sorted(snap["model_services"].items()):
        short = model.removeprefix("system.ai.")
        if not principals:
            lines.append(f'    "{short}" = {{}} # no direct grants today')
            continue
        lines.append(f'    "{short}" = {{')
        for p, privs in sorted(principals.items()):
            lines.append(f'      "{p}" = {hcl_list(privs)}')
        lines.append("    }")
    lines += ["  }", "}", ""]
    open(args.out, "w").write("\n".join(lines))
    print(f"wrote {args.out}: {len(snap['model_services'])} models")

if __name__ == "__main__":
    main()
