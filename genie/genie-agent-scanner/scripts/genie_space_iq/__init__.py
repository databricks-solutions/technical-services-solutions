"""genie_space_iq: deterministic IQ scan + safe apply for a Genie space.

A self-contained, LLM-free replication of Databricks Genie Workbench's
"IQ Scan + guided optimize" for a single Genie space/agent.

* :mod:`~genie_space_iq.model`   -- typed, read-only view of ``serialized_space``.
* :mod:`~genie_space_iq.checks`  -- the 12 deterministic checks.
* :mod:`~genie_space_iq.scoring` -- 0-12 IQ score + 3-tier maturity.
* :mod:`~genie_space_iq.levers`  -- scan-check -> optimization-lever bridge.
* :mod:`~genie_space_iq.report`  -- machine JSON + human markdown report.
* :mod:`~genie_space_iq.fixes`   -- deterministic fix application + unified diff.
* :mod:`~genie_space_iq.api`     -- Genie Spaces REST GET/PATCH (round-trip safe).
"""

from __future__ import annotations

from .api import GenieSpaceApi, SpaceListingError, fetch_uc_metadata, normalize_uc_table
from .checks import ALL_CHECKS, TOTAL_CHECKS, run_all_checks
from .fixes import (
    FixApplicationError,
    FixValidationError,
    apply_fixes,
    render_diff,
    validate_fixes,
)
from .levers import LEVER_NAMES, SCAN_CHECK_TO_LEVERS
from .model import Space, unwrap_serialized_space
from .report import build_report, render_markdown
from .scoring import calculate_score, get_maturity_label


class SpaceNameResolutionError(ValueError):
    """Raised when a --space-name matches zero or multiple Genie spaces."""


def resolve_space_name(api: GenieSpaceApi, name: str) -> str:
    """Resolve a Genie space title to its ``space_id`` (case-insensitive exact match).

    LISTS Genie spaces via ``api.list_spaces()`` (READ-ONLY) and matches ``name``
    against each space title, case-insensitively. Exactly one match returns that
    space's id. Zero or multiple matches raise :class:`SpaceNameResolutionError`
    with a message listing candidate ``title (id)`` pairs so the caller can pick.

    A blank/whitespace-only ``name`` is rejected up front, and listing entries
    without a usable title are excluded from the candidate set -- so a title-less
    space can never be resolved (not even by an empty name).
    """
    target = name.strip().casefold()
    if not target:
        raise SpaceNameResolutionError(
            "--space-name must be a non-empty title (got blank/whitespace)"
        )
    spaces = api.list_spaces()

    def _fmt(candidates: list[dict]) -> str:
        if not candidates:
            return "(none)"
        # Contract form is ``title (id)`` -- the candidate title is rendered
        # plainly (no quoting); only the SEARCHED name is quoted in the sentence.
        return "; ".join(
            f"{s.get('title')} ({s.get('space_id')})" for s in candidates
        )

    def _title_norm(space: dict) -> str:
        return str(space.get("title") or "").strip().casefold()

    # A title-less entry (missing/None/empty title) normalizes to "" and is never
    # a candidate -- it must not match, not even the (already-rejected) empty name.
    matches = [s for s in spaces if _title_norm(s) and _title_norm(s) == target]
    if len(matches) == 1:
        space_id = matches[0].get("space_id")
        if not space_id:
            raise SpaceNameResolutionError(
                f"space titled {name!r} has no space_id in the listing"
            )
        return str(space_id)
    if not matches:
        # Only show titled entries as candidates; a title-less entry can never be
        # resolved, so listing it as ``None (id)`` would only mislead.
        titled = [s for s in spaces if _title_norm(s)]
        raise SpaceNameResolutionError(
            f"no Genie space titled {name!r} (case-insensitive). "
            f"Available spaces: {_fmt(titled)}"
        )
    raise SpaceNameResolutionError(
        f"{len(matches)} Genie spaces match title {name!r} (case-insensitive); "
        f"use --space-id to disambiguate. Candidates: {_fmt(matches)}"
    )


def scan_space(
    document: object,
    optimization_run: dict | None = None,
    space_id: str | None = None,
    scanned_at: str | None = None,
    uc_metadata: dict | None = None,
) -> dict:
    """Run the full deterministic scan and return the machine-readable report.

    This is the pure scoring engine: a function of ``(document, uc_metadata,
    optimization_run)`` with no I/O. ``uc_metadata`` maps a full table name to
    ``{comment, table_type, columns:[{name, comment}]}``; when ``None`` the
    UC-dependent checks (1, 2) fall back to a config-only reading.
    """
    space = Space.from_document(
        document,
        optimization_run=optimization_run,
        space_id=space_id,
        uc_metadata=uc_metadata,
    )
    checks = run_all_checks(space)
    missing = space.uc_missing_identifiers
    if not space.uc_available:
        uc_status = "unavailable"
    elif missing:
        uc_status = "partial"
    else:
        uc_status = "full"
    return build_report(
        checks,
        space_id=space_id,
        scanned_at=scanned_at,
        uc_available=space.uc_available,
        uc_status=uc_status,
        uc_missing=sorted(missing),
    )


__all__ = [
    "ALL_CHECKS",
    "TOTAL_CHECKS",
    "LEVER_NAMES",
    "SCAN_CHECK_TO_LEVERS",
    "GenieSpaceApi",
    "Space",
    "FixApplicationError",
    "FixValidationError",
    "SpaceListingError",
    "SpaceNameResolutionError",
    "apply_fixes",
    "build_report",
    "calculate_score",
    "fetch_uc_metadata",
    "get_maturity_label",
    "normalize_uc_table",
    "render_diff",
    "render_markdown",
    "resolve_space_name",
    "run_all_checks",
    "scan_space",
    "unwrap_serialized_space",
    "validate_fixes",
]
