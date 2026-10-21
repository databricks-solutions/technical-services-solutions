"""Scan-check -> optimization-lever bridge.

Ported from the Genie Space Optimizer (GSO) ``SCAN_CHECK_TO_LEVERS`` map in the
public Databricks Genie Workbench accelerator
(databricks-solutions/databricks-genie-workbench; see NOTICE.md), enriched with a
``fixable`` flag and a human description.

Per the source, checks 1, 6, 10, 11 and 12 are intentionally absent from the
lever map -- no single config lever can remediate them:

    2 -> [1]  # Table descriptions   -> Lever 1 (Tables & Columns)
    3 -> [1]  # Column descriptions  -> Lever 1
    4 -> [5]  # Text instructions    -> Lever 5 (Instructions)
    5 -> [4]  # Join specifications  -> Lever 4 (Joins)
    7 -> [6]  # 8+ example SQLs       -> Lever 6 (SQL Expressions)
    8 -> [6]  # SQL snippets          -> Lever 6
    9 -> [1]  # Entity/format match   -> Lever 1

Note: ``fixable`` here describes whether a GSO *lever* addresses the check. It is
distinct from whether :mod:`genie_space_iq.fixes` can *apply* a caller-drafted
patch (that path can also target benchmarks/sample questions).
"""

from __future__ import annotations

from typing import Any

LEVER_NAMES: dict[int, str] = {
    1: "Tables & Columns",
    2: "Metric Views",
    3: "Table-Valued Functions",
    4: "Join Specifications",
    5: "Genie Space Instructions",
    6: "SQL Expressions",
}

# Deterministic fix-order, mirroring the GSO default lever order [1, 2, 3, 4, 5, 6].
DEFAULT_LEVER_ORDER: list[int] = [1, 2, 3, 4, 5, 6]

SCAN_CHECK_TO_LEVERS: dict[int, dict[str, Any]] = {
    1: {
        "fixable": False,
        "levers": [],
        "description": "Add >=1 table or metric view; no lever can synthesize a data source.",
    },
    2: {
        "fixable": True,
        "levers": [1],
        "description": "Add table descriptions (Lever 1: Tables & Columns).",
    },
    3: {
        "fixable": True,
        "levers": [1],
        "description": "Add column descriptions and synonyms (Lever 1: Tables & Columns).",
    },
    4: {
        "fixable": True,
        "levers": [5],
        "description": "Add or expand text instructions (Lever 5: Instructions).",
    },
    5: {
        "fixable": True,
        "levers": [4],
        "description": "Add join specifications between related tables (Lever 4: Joins).",
    },
    6: {
        "fixable": False,
        "levers": [],
        "description": "Reduce to <=12 data sources or split into multiple spaces.",
    },
    7: {
        "fixable": True,
        "levers": [6],
        "description": "Add curated example question/SQL pairs (Lever 6: SQL Expressions).",
    },
    8: {
        "fixable": True,
        "levers": [6],
        "description": "Add reusable SQL snippets: filters, measures, expressions (Lever 6).",
    },
    9: {
        "fixable": True,
        "levers": [1],
        "description": "Enable entity/format matching on categorical columns (Lever 1).",
    },
    10: {
        "fixable": False,
        "levers": [],
        "description": "Author >=10 benchmark questions with ground-truth SQL (no lever).",
    },
    11: {
        "fixable": False,
        "levers": [],
        "description": "Run an optimization workflow. Not a config lever.",
    },
    12: {
        "fixable": False,
        "levers": [],
        "description": "Raise optimization accuracy to >=85% by iterating. Not a config lever.",
    },
}


def levers_for_check(check_id: int) -> dict[str, Any]:
    """Return the lever metadata for a check id (safe default when unmapped)."""
    return SCAN_CHECK_TO_LEVERS.get(
        check_id, {"fixable": False, "levers": [], "description": ""}
    )
