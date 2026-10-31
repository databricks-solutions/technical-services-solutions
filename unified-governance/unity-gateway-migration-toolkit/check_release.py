#!/usr/bin/env python3
"""Check that the committed installer matches the sources and the versions agree. Run before a release.

- rebuilds the installer into a temporary folder (make_installer.build, no mtime check) and byte-compares it with
  INSTALL_unity_gateway_migration_toolkit_<version>.py in this folder
- checks that __version__ (ug_migration_planner.py), version (app/frontend/package.json) and toolkit_version
  (databricks.yml) are the same

Exit 0 when everything matches, 1 with a message per problem otherwise. Stdlib only.
"""

import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_installer  # noqa: E402


def versions() -> dict[str, str]:
    with open(os.path.join(HERE, "ug_migration_planner.py")) as f:
        planner = f.read()
    with open(os.path.join(HERE, "app/frontend/package.json")) as f:
        pkg = json.load(f)
    with open(os.path.join(HERE, "databricks.yml")) as f:
        bundle = f.read()
    bundle_v = re.search(r'toolkit_version:\n\s+description:[^\n]*\n\s+default: "(.+)"', bundle)
    return {
        "ug_migration_planner.py __version__": re.search(r'^__version__ = "(.+)"', planner, re.M).group(1),
        "app/frontend/package.json version": pkg["version"],
        "databricks.yml toolkit_version": bundle_v.group(1) if bundle_v else "(missing)",
    }


def main() -> int:
    problems = []
    v = versions()
    if len(set(v.values())) != 1:
        problems += [f"version mismatch: {name} = {value}" for name, value in v.items()]
    version = v["ug_migration_planner.py __version__"]
    committed = os.path.join(HERE, f"INSTALL_unity_gateway_migration_toolkit_{version.replace('.', '_')}.py")
    if not os.path.exists(committed):
        problems.append(f"{os.path.basename(committed)} is not committed (run ./package.sh and copy it here)")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            built = make_installer.build(tmp, check_fresh=False)
            with open(built, "rb") as a, open(committed, "rb") as b:
                if a.read() != b.read():
                    problems.append(f"{os.path.basename(committed)} doesn't match a fresh build from the sources: "
                                    "rebuild with ./package.sh and commit the new installer")
    for p in problems:
        print("FAIL:", p)
    if not problems:
        print(f"OK: toolkit {version}, installer matches the sources")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
