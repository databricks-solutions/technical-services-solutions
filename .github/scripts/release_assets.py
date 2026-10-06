#!/usr/bin/env python3
"""Cut a new GitHub release for every asset in .github/releases.yml whose folder changed.

For each manifest entry, the latest tag is the highest <slug>-vN (legacy <slug>-vN.x.y
tags count as N). If no tag exists, release v1. Otherwise, if the folder differs between
that tag and HEAD, release v(N+1). The zip contains only the asset folder (tracked files).

Usage: release_assets.py [--dry-run]   (needs GH_TOKEN and GITHUB_REPOSITORY unless --dry-run)
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

import yaml

MANIFEST = ".github/releases.yml"
OUT_DIR = "dist"

BODY = """v{n} release of **{name}** ({kind}).

Source: [`{path}`](https://github.com/{repo}/tree/{tag}/{url_path})

Download `{tag}.zip` below. It contains only this asset. The auto-generated "Source code" \
archives contain the entire repository."""


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def latest_version(slug):
    """Return the highest N among <slug>-vN tags (0 if none)."""
    pattern = re.compile(rf"^{re.escape(slug)}-v(\d+)(?:\.\d+)*$")
    best = 0, None
    for tag in git("tag", "--list", f"{slug}-v*").stdout.split():
        m = pattern.match(tag)
        if m and int(m.group(1)) > best[0]:
            best = int(m.group(1)), tag
    return best


def changed_since(tag, path):
    return git("diff", "--quiet", tag, "HEAD", "--", path, check=False).returncode != 0


def build_zip(tag, path):
    out = os.path.join(OUT_DIR, f"{tag}.zip")
    git("archive", "--format=zip", f"--prefix={PurePosixPath(path).name}/",
        "-o", out, f"HEAD:{path}")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if os.environ.get("GITHUB_ACTIONS") == "true":
        ref = os.environ.get("GITHUB_REF", "")
        if ref != "refs/heads/main":
            sys.exit(f"refusing to publish from {ref or '(unset)'}; only refs/heads/main is allowed")

    repo = os.environ.get("GITHUB_REPOSITORY", "databricks-solutions/technical-services-solutions")
    target = os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD").stdout.strip()
    with open(MANIFEST) as f:
        entries = yaml.safe_load(f)

    os.makedirs(OUT_DIR, exist_ok=True)
    planned = []
    for e in entries:
        slug, path = e["slug"], e["path"]
        if not os.path.isdir(path):
            sys.exit(f"{slug}: path does not exist: {path!r}")
        n, tag = latest_version(slug)
        if tag and not changed_since(tag, path):
            print(f"  {slug}: unchanged since {tag}")
            continue
        new_tag = f"{slug}-v{n + 1}"
        print(f"+ {slug}: {tag or '(no tag)'} -> {new_tag}")
        planned.append((e, n + 1, new_tag))

    for e, n, tag in planned:
        zip_path = build_zip(tag, e["path"])
        if args.dry_run:
            print(f"[dry-run] built {zip_path}")
            continue
        body = BODY.format(n=n, name=e["name"], kind=e["kind"], path=e["path"], repo=repo,
                           tag=tag, url_path=e["path"].replace(" ", "%20"))
        subprocess.run(["gh", "release", "create", tag, zip_path, "--repo", repo,
                        "--target", target, "--title", f"{e['name']} v{n}",
                        "--notes", body, "--latest=false"], check=True)
        print(f"released {tag}")

    print(f"{len(planned)} release(s) {'planned' if args.dry_run else 'created'}.")


if __name__ == "__main__":
    main()
