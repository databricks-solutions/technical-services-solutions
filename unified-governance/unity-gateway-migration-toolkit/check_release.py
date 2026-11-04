#!/usr/bin/env python3
"""Check that the committed installer matches the sources and the versions agree. Run before a release.

- rebuilds the installer into a temporary folder (make_installer.build, no mtime check) and byte-compares it with
  INSTALL_unity_gateway_migration_toolkit_<version>.py in this folder
- checks that __version__ (ug_migration_planner.py), version (app/frontend/package.json) and toolkit_version
  (databricks.yml) are the same
- checks that every installer or zip file name the shipped guides mention (GUIDES) carries that version, so a guide
  never tells people to import a file the release doesn't ship

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
    lock_path = os.path.join(HERE, "app/frontend/package-lock.json")
    lock = json.load(open(lock_path)) if os.path.exists(lock_path) else {}
    with open(os.path.join(HERE, "databricks.yml")) as f:
        bundle = f.read()
    bundle_v = re.search(r'toolkit_version:\n\s+description:[^\n]*\n\s+default: "(.+)"', bundle)
    return {
        "ug_migration_planner.py __version__": re.search(r'^__version__ = "(.+)"', planner, re.M).group(1),
        "app/frontend/package.json version": pkg["version"],
        **({"app/frontend/package-lock.json version": lock.get("version", "(missing)"),
            "app/frontend/package-lock.json root package version":
                (lock.get("packages") or {}).get("", {}).get("version", "(missing)")} if lock else {}),
        "databricks.yml toolkit_version": bundle_v.group(1) if bundle_v else "(missing)",
    }


# A versioned customer file name in the docs: INSTALL_..._0_10_1.py or unity-gateway-migration-toolkit-0.10.1.zip.
VERSIONED_NAME_RE = re.compile(r"INSTALL_unity_gateway_migration_toolkit_(\d+_\d+_\d+)\.py"
                               r"|unity-gateway-migration-toolkit-(\d+\.\d+\.\d+)\.zip")


# The guides that ship with the toolkit. Dev notes (NOTES_*.md) keep old file names on purpose, so they aren't checked.
GUIDES = ("README.md", "USER_GUIDE.md", "HOW_TO_READ.md", "DEVELOPING.md")


def stale_doc_names(version: str) -> list[str]:
    """Versioned installer or zip names in the guides that don't match version (file:line: name)."""
    out = []
    for name in GUIDES:
        if not os.path.exists(os.path.join(HERE, name)):
            continue
        with open(os.path.join(HERE, name)) as f:
            for i, line in enumerate(f, 1):
                for m in VERSIONED_NAME_RE.finditer(line):
                    found = (m.group(1) or "").replace("_", ".") or m.group(2)
                    if found != version:
                        out.append(f"{name}:{i}: {m.group(0)}")
    return out


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
    problems += [f"{loc} names another version's file: use the {version} name" for loc in stale_doc_names(version)]
    for p in problems:
        print("FAIL:", p)
    if not problems:
        print(f"OK: toolkit {version}, installer matches the sources, guides name {version} files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
