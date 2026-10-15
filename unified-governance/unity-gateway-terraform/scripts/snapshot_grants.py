#!/usr/bin/env python3
"""Step 1: snapshot the current grants on system.ai model services (read-only).

Writes a JSON file that is both the input for the Terraform config generator and the rollback copy.

  python3 scripts/snapshot_grants.py --profile <workspace-profile> --out snapshot/grants.json
"""
import argparse, datetime, json, subprocess, sys
from collections import Counter

def dbx(profile, *args):
    out = subprocess.run(["databricks", *args, "--profile", profile, "-o", "json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else {}

def grants(profile, securable_type, name):
    d = dbx(profile, "grants", "get", securable_type, name)
    return {a["principal"]: sorted(a.get("privileges", [])) for a in d.get("privilege_assignments", [])}

def list_services(profile, attempts):
    # The list API sometimes returns an empty result. Call it several times and keep the
    # largest result; stop if no two calls agree.
    seen = []
    for _ in range(attempts):
        names, token = [], None
        while True:
            path = "/api/2.1/unity-catalog/model-services?parent=schemas/system.ai&page_size=100"
            if token:
                path += f"&page_token={token}"
            d = dbx(profile, "api", "get", path)
            names += [s["name"].split("/", 1)[1] for s in d.get("model_services", [])]
            token = d.get("next_page_token")
            if not token:
                break
        seen.append(tuple(sorted(names)))
    counts = Counter(seen)
    best = max(seen, key=len)
    if not best or counts[best] < 2:
        sys.exit(f"Service list is not stable: sizes {[len(s) for s in seen]}. Run again.")
    return list(best)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempts", type=int, default=6)
    args = ap.parse_args()

    services = list_services(args.profile, args.attempts)
    snap = {
        "taken_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "metastore_id": dbx(args.profile, "metastores", "current")["metastore_id"],
        "catalog_system": grants(args.profile, "catalog", "system"),
        "schema_system_ai": grants(args.profile, "schema", "system.ai"),
        "model_services": {s: grants(args.profile, "model_service", s) for s in services},
    }
    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(snap, f, indent=2, sort_keys=True)
    empty = [s for s, g in snap["model_services"].items() if not g]
    print(f"{len(services)} model services, {len(empty)} with no direct grants -> {args.out}")
    if "EXECUTE" in snap["schema_system_ai"].get("account users", []):
        print("WARNING: account users has EXECUTE on schema system.ai; every model inherits it.")

if __name__ == "__main__":
    main()
