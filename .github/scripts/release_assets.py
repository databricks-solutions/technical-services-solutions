#!/usr/bin/env python3
"""Keep one current GitHub release per asset in .github/releases.yml.

Each asset uses a stable <slug>-latest release. If its folder changed since that tag,
the attached zip is replaced and the tag moves to HEAD. Zips contain only tracked asset files.

Runs in two steps so every zip is attested before it is published:
  release_assets.py build     plan changed assets, zip them into dist/, write dist/plan.json
  release_assets.py publish   upload the zips listed in dist/plan.json, then move each tag

`build` only reads from GitHub, so running it locally is a dry run.
Both steps need GH_TOKEN (or a logged-in gh) and use GITHUB_REPOSITORY when set.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import PurePosixPath

import yaml

MANIFEST = ".github/releases.yml"
OUT_DIR = "dist"
PLAN = os.path.join(OUT_DIR, "plan.json")

BODY = """Current release of **{name}** ({kind}).

Source: [`{path}`](https://github.com/{repo}/tree/{tag}/{url_path})

Download `{slug}.zip` below. It contains only this asset. The auto-generated "Source code" \
archives contain the entire repository.

This release and its zip are updated in place whenever the asset changes on `main`."""


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def gh(*args, check=True, capture_output=False):
    return subprocess.run(
        ["gh", *args], check=check, capture_output=capture_output, text=True
    )


def is_ancestor(tag):
    return git("merge-base", "--is-ancestor", tag, "HEAD", check=False).returncode == 0


def changed_since(tag, path):
    return git("diff", "--quiet", tag, "HEAD", "--", path, check=False).returncode != 0


def release_exists(repo, tag):
    return (
        gh("release", "view", tag, "--repo", repo, check=False, capture_output=True).returncode
        == 0
    )


def set_tag(repo, tag, target, exists):
    if exists:
        gh("api", "--method", "PATCH", f"repos/{repo}/git/refs/tags/{tag}",
           "-f", f"sha={target}", "-F", "force=true")
    else:
        gh("api", "--method", "POST", f"repos/{repo}/git/refs",
           "-f", f"ref=refs/tags/{tag}", "-f", f"sha={target}")


def build(repo, target):
    with open(MANIFEST) as f:
        entries = yaml.safe_load(f)
    slugs = [e["slug"] for e in entries]
    if len(set(slugs)) != len(slugs):
        sys.exit(f"{MANIFEST}: duplicate slugs are not allowed")

    shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR)
    planned = []
    for e in entries:
        slug, path = e["slug"], e["path"]
        if not os.path.isdir(path):
            sys.exit(f"{slug}: path does not exist: {path!r}")
        tag = f"{slug}-latest"
        tag_exists = tag in git("tag", "--list", tag).stdout.split()
        # A tag that HEAD doesn't contain means this run is older than the last
        # release (e.g. a re-run of an old workflow); publishing would roll it back.
        if tag_exists and not is_ancestor(tag):
            print(f"  {slug}: {tag} is not an ancestor of HEAD; skipping")
            continue
        has_release = release_exists(repo, tag)
        if tag_exists and has_release and not changed_since(tag, path):
            print(f"  {slug}: current at {tag}")
            continue
        zip_path = os.path.join(OUT_DIR, f"{slug}.zip")
        git("archive", "--format=zip", f"--prefix={PurePosixPath(path).name}/",
            "-o", zip_path, f"HEAD:{path}")
        print(f"+ {slug}: {'update' if has_release else 'create'} {tag}")
        planned.append({"entry": e, "tag": tag, "zip": zip_path,
                        "tag_exists": tag_exists, "has_release": has_release})

    with open(PLAN, "w") as f:
        json.dump({"target": target, "assets": planned}, f, indent=2)
    print(f"{len(planned)} release(s) planned in {PLAN}.")


def publish(repo):
    with open(PLAN) as f:
        plan = json.load(f)
    target = plan["target"]
    for p in plan["assets"]:
        e, tag, zip_path = p["entry"], p["tag"], p["zip"]
        if not os.path.isfile(zip_path):
            sys.exit(f"{e['slug']}: missing {zip_path}; run build first")
        body = BODY.format(name=e["name"], kind=e["kind"], path=e["path"], repo=repo,
                           tag=tag, slug=e["slug"], url_path=e["path"].replace(" ", "%20"))
        if p["has_release"]:
            gh("release", "upload", tag, zip_path, "--repo", repo, "--clobber")
            gh("release", "edit", tag, "--repo", repo, "--title", e["name"], "--notes", body)
            # The tag is the current-state marker, so move/create it only after
            # the asset and release metadata were updated successfully.
            set_tag(repo, tag, target, p["tag_exists"])
            print(f"updated {tag}")
        else:
            gh("release", "create", tag, zip_path, "--repo", repo, "--target", target,
               "--title", e["name"], "--notes", body, "--latest=false")
            if p["tag_exists"]:
                set_tag(repo, tag, target, exists=True)
            print(f"created {tag}")
    print(f"{len(plan['assets'])} release(s) published.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "publish"])
    args = parser.parse_args()

    if os.environ.get("GITHUB_ACTIONS") == "true":
        ref = os.environ.get("GITHUB_REF", "")
        if ref != "refs/heads/main":
            sys.exit(f"refusing to publish from {ref or '(unset)'}; only refs/heads/main is allowed")

    repo = os.environ.get("GITHUB_REPOSITORY", "databricks-solutions/technical-services-solutions")
    if args.command == "build":
        target = os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD").stdout.strip()
        build(repo, target)
    else:
        publish(repo)


if __name__ == "__main__":
    main()
