#!/usr/bin/env python3
"""scan.py -- deterministic, READ-ONLY IQ scan of a single Genie space.

No LLM. No writes. Same input => same output.

Usage:
    # Live (Databricks SDK default auth): fetches the serialized_space AND
    # per-table Unity Catalog metadata (read-only; no SQL warehouse).
    python scripts/scan.py --space-id <ID> [--profile P] [--json-out scan.json] [--md-out scan.md]

    # Live by title: resolve a Genie space name to its id via a READ-ONLY listing
    # (case-insensitive exact match; must resolve to exactly one space), then scan.
    python scripts/scan.py --space-name "My Genie Space" [--profile P]

    # Offline (no API): a raw serialized_space, an API export, or an envelope
    # {"serialized_space": {...}, "optimization_run": {...}}. Pass UC metadata
    # (full-table-name -> {comment, table_type, columns:[{name, comment}]}) via
    # --uc-metadata-file so checks 1 and 2 match the Workbench 1:1; without it
    # those checks fall back to a config-only reading.
    python scripts/scan.py --serialized-space-file <path.json> [--uc-metadata-file <path.json>]

Checks 11 and 12 (optimization outcomes) require an optimization run. Supply it
via an envelope sibling key or --optimization-run-file; without one, those two
checks fail and a config-perfect space tops out at "Ready to Optimize".
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from genie_space_iq import render_markdown, scan_space


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic IQ scan of a Genie space.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--space-id", help="Genie space id (fetched via Databricks SDK).")
    source.add_argument(
        "--space-name",
        help="Genie space title to resolve to an id via a READ-ONLY space listing "
        "(case-insensitive exact match; must resolve to exactly one space).",
    )
    source.add_argument(
        "--serialized-space-file",
        help="Path to a serialized_space JSON, API export, or envelope (offline; no API).",
    )
    parser.add_argument(
        "--optimization-run-file",
        help="Optional optimization_run JSON to feed checks 11-12.",
    )
    parser.add_argument(
        "--uc-metadata-file",
        help="Optional UC metadata JSON (offline): full-table-name -> "
        "{comment, table_type, columns:[{name, comment}]}.",
    )
    parser.add_argument("--json-out", help="Write the machine-readable report JSON here.")
    parser.add_argument("--md-out", help="Write the human-readable markdown report here.")
    parser.add_argument("--profile", help="Databricks CLI/SDK profile for --space-id mode.")
    parser.add_argument(
        "--scanned-at",
        help="Optional timestamp string recorded in the report (omitted by default "
        "to keep output deterministic).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    optimization_run = (
        _load_json(args.optimization_run_file) if args.optimization_run_file else None
    )

    uc_metadata: Any | None = None
    space_id = args.space_id

    if args.serialized_space_file:
        document = _load_json(args.serialized_space_file)
        if args.uc_metadata_file:
            uc_metadata = _load_json(args.uc_metadata_file)
    else:
        # Live fetch. Imported lazily so offline mode never needs the SDK.
        from genie_space_iq import (
            GenieSpaceApi,
            Space,
            SpaceListingError,
            SpaceNameResolutionError,
            fetch_uc_metadata,
            resolve_space_name,
        )

        api = GenieSpaceApi(profile=args.profile)

        # --space-name resolves to a space_id via a READ-ONLY listing; from there
        # the flow is identical to --space-id. Use ``is not None`` so an empty
        # string ("--space-name ''") still routes through the resolver, which
        # rejects it clearly instead of falling through to get_space(None).
        if args.space_name is not None:
            try:
                space_id = resolve_space_name(api, args.space_name)
            except (SpaceNameResolutionError, SpaceListingError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2

        document = api.get_space(space_id)

        # Read-only UC enrichment for each declared data source. Degrade
        # gracefully: a per-table failure is a warning, not a crash.
        identifiers = Space.from_document(document).data_source_identifiers
        fetched, warnings = fetch_uc_metadata(api, identifiers)
        for identifier, err in warnings:
            print(f"WARNING: UC metadata unavailable for {identifier}: {err}", file=sys.stderr)
        if fetched:
            uc_metadata = fetched
        else:
            print(
                "WARNING: no UC metadata available; UC-dependent checks (1, 2) "
                "run config-only",
                file=sys.stderr,
            )

    report = scan_space(
        document,
        optimization_run=optimization_run,
        space_id=space_id,
        scanned_at=args.scanned_at,
        uc_metadata=uc_metadata,
    )
    markdown = render_markdown(report)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    if args.md_out:
        with open(args.md_out, "w", encoding="utf-8") as handle:
            handle.write(markdown + "\n")

    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
