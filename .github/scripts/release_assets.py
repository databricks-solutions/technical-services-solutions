#!/usr/bin/env python3
"""Keep one current GitHub release per asset in .github/releases.yml.

Each asset uses a stable <slug>-latest release. If its folder changed since that tag,
move the tag to HEAD and replace the attached zip. On first migration, create the stable
release and remove legacy <slug>-vN releases/tags. Zips contain only tracked asset files.

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

BODY = """Current release of **{name}** ({kind}).

Source: [`{path}`](https://github.com/{repo}/tree/{tag}/{url_path})

Download `{slug}.zip` below. It contains only this asset. The auto-generated "Source code" \
archives contain the entire repository.

This release and its zip are updated in place whenever the asset changes on `main`."""


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def legacy_tags(slug):
    """Return legacy version tags for an asset."""
    pattern = re.compile(rf"^{re.escape(slug)}-v\d+(?:\.\d+)*$")
    return [
        tag
        for tag in git("tag", "--list", f"{slug}-v*").stdout.split()
        if pattern.match(tag)
    ]


def changed_since(tag, path):
    return git("diff", "--quiet", tag, "HEAD", "--", path, check=False).returncode != 0


def build_zip(slug, path):
    out = os.path.join(OUT_DIR, f"{slug}.zip")
    git("archive", "--format=zip", f"--prefix={PurePosixPath(path).name}/",
        "-o", out, f"HEAD:{path}")
    return out


def gh(*args, check=True, capture_output=False):
    return subprocess.run(
        ["gh", *args], check=check, capture_output=capture_output, text=True
    )


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


def delete_legacy(repo, tags):
    for tag in tags:
        # --cleanup-tag removes the tag when a release exists. The API call also
        # cleans up orphaned tags; 404 is expected if --cleanup-tag removed it.
        release_result = gh(
            "release", "delete", tag, "--repo", repo, "--cleanup-tag", "--yes",
            check=False, capture_output=True
        )
        tag_result = gh(
            "api", "--method", "DELETE", f"repos/{repo}/git/refs/tags/{tag}",
            check=False, capture_output=True
        )
        errors = f"{release_result.stderr}\n{tag_result.stderr}"
        if release_result.returncode and tag_result.returncode and "Not Found" not in errors:
            sys.exit(f"failed to remove legacy release/tag {tag}:\n{errors.strip()}")
        print(f"removed legacy release/tag {tag}")


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
    slugs = [e["slug"] for e in entries]
    if len(set(slugs)) != len(slugs):
        sys.exit(f"{MANIFEST}: duplicate slugs are not allowed")

    os.makedirs(OUT_DIR, exist_ok=True)
    planned = []
    cleanup = []
    for e in entries:
        slug, path = e["slug"], e["path"]
        if not os.path.isdir(path):
            sys.exit(f"{slug}: path does not exist: {path!r}")
        tag = f"{slug}-latest"
        old_tags = legacy_tags(slug)
        if old_tags:
            cleanup.append((slug, old_tags))
        tag_exists = tag in git("tag", "--list", tag).stdout.split()
        has_release = tag_exists if args.dry_run else release_exists(repo, tag)
        if tag_exists and has_release and not changed_since(tag, path):
            print(f"  {slug}: current at {tag}")
            continue
        action = "update" if has_release else "create"
        print(f"+ {slug}: {action} {tag}")
        planned.append((e, tag, tag_exists, has_release))

    for e, tag, tag_exists, has_release in planned:
        slug = e["slug"]
        zip_path = build_zip(slug, e["path"])
        if args.dry_run:
            print(f"[dry-run] built {zip_path}")
            continue
        body = BODY.format(name=e["name"], kind=e["kind"], path=e["path"], repo=repo,
                           tag=tag, slug=slug, url_path=e["path"].replace(" ", "%20"))
        if has_release:
            gh("release", "upload", tag, zip_path, "--repo", repo, "--clobber")
            gh("release", "edit", tag, "--repo", repo, "--title", e["name"], "--notes", body)
            # The tag is the current-state marker, so move/create it only after
            # the asset and release metadata were updated successfully.
            set_tag(repo, tag, target, tag_exists)
            print(f"updated {tag}")
        else:
            gh("release", "create", tag, zip_path, "--repo", repo, "--target", target,
               "--title", e["name"], "--notes", body, "--latest=false")
            if tag_exists:
                set_tag(repo, tag, target, exists=True)
            print(f"created {tag}")

    if args.dry_run:
        for slug, tags in cleanup:
            print(f"[dry-run] would remove legacy {slug} releases/tags: {', '.join(tags)}")
    else:
        for _, tags in cleanup:
            delete_legacy(repo, tags)

    verb = "planned" if args.dry_run else "updated"
    print(f"{len(planned)} current release(s) {verb}.")


if __name__ == "__main__":
    main()
