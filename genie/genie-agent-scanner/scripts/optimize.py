#!/usr/bin/env python3
"""optimize.py -- deterministically APPLY caller-drafted fixes to a Genie space.

No LLM. Fix content is drafted by the host agent and passed IN as structured
JSON (see fixes.json schema in scripts/README.md and genie_space_iq/fixes.py).

Default = DRY-RUN: print a unified diff of serialized_space (before -> after).
--apply performs a round-trip PATCH that PRESERVES all unknown/unrecognized fields.

Usage:
    # Dry-run against the live space (fetch, diff, do not write):
    python scripts/optimize.py --space-id <ID> --fixes-file fixes.json

    # Dry-run fully offline (no API), diffing against a local space file:
    python scripts/optimize.py --serialized-space-file space.json --fixes-file fixes.json

    # Apply (round-trip PATCH):
    python scripts/optimize.py --space-id <ID> --fixes-file fixes.json --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from genie_space_iq import (
    apply_fixes,
    render_diff,
    unwrap_serialized_space,
    validate_fixes,
)


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministically apply caller-drafted fixes to a Genie space."
    )
    parser.add_argument("--space-id", help="Genie space id (required for fetch/--apply).")
    parser.add_argument(
        "--serialized-space-file",
        help="Offline source for the 'before' space (no API fetch).",
    )
    parser.add_argument("--fixes-file", required=True, help="Path to fixes.json.")
    parser.add_argument(
        "--scan-file",
        help="Optional scan.json; annotates the summary with the checks addressed.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the PATCH. Default is a dry-run diff only.",
    )
    parser.add_argument("--out", help="In dry-run, write the patched serialized_space here.")
    parser.add_argument("--profile", help="Databricks CLI/SDK profile.")
    return parser


def _addressed_checks(fixes: list[dict[str, Any]]) -> list[int]:
    ids = sorted({f["check_id"] for f in fixes if isinstance(f.get("check_id"), int)})
    return ids


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    fixes = validate_fixes(_load_json(args.fixes_file))

    api = None
    if args.serialized_space_file:
        before = unwrap_serialized_space(_load_json(args.serialized_space_file))
    else:
        if not args.space_id:
            print(
                "error: provide --serialized-space-file or --space-id", file=sys.stderr
            )
            return 2
        from genie_space_iq import GenieSpaceApi

        api = GenieSpaceApi(profile=args.profile)
        before = api.get_space(args.space_id)["serialized_space"]

    after = apply_fixes(before, fixes)

    addressed = _addressed_checks(fixes)
    summary = f"{len(fixes)} fix(es)"
    if addressed:
        summary += f" addressing check(s) {', '.join(str(c) for c in addressed)}"

    if args.apply:
        if not args.space_id:
            print("error: --apply requires --space-id", file=sys.stderr)
            return 2
        if api is None:
            from genie_space_iq import GenieSpaceApi

            api = GenieSpaceApi(profile=args.profile)
        api.patch_space(args.space_id, after)
        print(f"Applied {summary} to space {args.space_id} via PATCH.")
        return 0

    diff = render_diff(before, after, space_id=args.space_id)
    print(f"DRY-RUN: {summary}. No changes written (use --apply to PATCH).")
    print()
    print(diff if diff else "(no changes -- fixes produced an identical space)")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(after, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
