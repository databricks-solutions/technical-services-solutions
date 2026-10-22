"""Render a scan result as both machine JSON and human markdown.

Deterministic by construction: ``scanned_at`` is only populated when the caller
supplies it, so ``same input => same output`` holds (no wall-clock timestamp is
injected). Output lists (findings, next steps) are capped at 8, matching the
Workbench scanner.
"""

from __future__ import annotations

from typing import Any

from .levers import DEFAULT_LEVER_ORDER, LEVER_NAMES, levers_for_check
from .scoring import TOTAL_CHECKS, calculate_score, get_maturity_label

MAX_LIST_ITEMS = 8

_SEVERITY_ICON = {"pass": "PASS", "warning": "WARN", "fail": "FAIL"}


def _next_step_sort_key(check: dict[str, Any]) -> tuple[int, int, int]:
    severity_rank = 0 if check["severity"] == "fail" else 1
    levers = check.get("levers") or []
    lever_rank = DEFAULT_LEVER_ORDER.index(levers[0]) if levers else len(DEFAULT_LEVER_ORDER)
    return (severity_rank, lever_rank, check["id"])


def _actionable(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Checks that failed or warned, in deterministic fix-order."""
    items = [c for c in checks if not c["passed"] or c["severity"] == "warning"]
    return sorted(items, key=_next_step_sort_key)


def build_report(
    checks: list[dict[str, Any]],
    space_id: str | None = None,
    maturity: str | None = None,
    score: int | None = None,
    scanned_at: str | None = None,
    uc_available: bool | None = None,
    uc_status: str | None = None,
    uc_missing: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the machine-readable scan report."""
    ordered = sorted(checks, key=lambda c: c["id"])
    if score is None:
        score = calculate_score(ordered)
    if maturity is None:
        maturity = get_maturity_label(ordered)

    actionable = _actionable(ordered)
    findings = [
        {
            "check_id": c["id"],
            "name": c["name"],
            "severity": c["severity"],
            "evidence": c["evidence"],
        }
        for c in actionable
    ][:MAX_LIST_ITEMS]

    next_steps = []
    for c in actionable[:MAX_LIST_ITEMS]:
        info = levers_for_check(c["id"])
        next_steps.append(
            {
                "check_id": c["id"],
                "name": c["name"],
                "severity": c["severity"],
                "fixable": info["fixable"],
                "levers": info["levers"],
                "lever_names": [LEVER_NAMES[i] for i in info["levers"]],
                "action": info["description"]
                or "Structural - requires a manual change (no automated lever).",
            }
        )

    report: dict[str, Any] = {
        "space_id": space_id,
        "score": score,
        "total": TOTAL_CHECKS,
        "maturity": maturity,
        "uc_available": uc_available,
        "uc_status": uc_status,
        "uc_missing": uc_missing if uc_missing is not None else [],
        "checks": ordered,
        "findings": findings,
        "next_steps": next_steps,
        "scanned_at": scanned_at,
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render the report as a human-readable markdown document."""
    lines: list[str] = []
    space_id = report.get("space_id")
    header = "# Genie Space IQ Scan"
    if space_id:
        header += f" - `{space_id}`"
    lines.append(header)
    lines.append("")
    lines.append(
        f"**Score:** {report['score']} / {report['total']}  |  "
        f"**Maturity:** {report['maturity']}"
    )
    if report.get("scanned_at"):
        lines.append(f"**Scanned at:** {report['scanned_at']}")
    uc_status = report.get("uc_status")
    if uc_status == "unavailable" or report.get("uc_available") is False:
        lines.append(
            "**UC metadata:** not available - UC-dependent checks (1, 2) ran config-only"
        )
    elif uc_status == "partial":
        missing = report.get("uc_missing") or []
        detail = ", ".join(missing) if missing else "some data sources"
        lines.append(
            f"**UC metadata:** partial - {len(missing)} data source(s) lacked UC metadata "
            f"(best-effort): {detail}"
        )
    lines.append("")

    lines.append("## Checks")
    lines.append("")
    lines.append("| # | Check | Result | Evidence |")
    lines.append("|---|-------|--------|----------|")
    for c in report["checks"]:
        result = _SEVERITY_ICON.get(c["severity"], c["severity"])
        evidence = str(c["evidence"]).replace("|", "\\|")
        lines.append(f"| {c['id']} | {c['name']} | {result} | {evidence} |")
    lines.append("")

    findings = report.get("findings") or []
    lines.append(f"## Findings ({len(findings)})")
    lines.append("")
    if findings:
        for f in findings:
            icon = _SEVERITY_ICON.get(f["severity"], f["severity"])
            lines.append(f"- [{icon}] Check {f['check_id']} - {f['name']}: {f['evidence']}")
    else:
        lines.append("- None. All checks pass.")
    lines.append("")

    next_steps = report.get("next_steps") or []
    lines.append("## Ranked next steps")
    lines.append("")
    if next_steps:
        for i, step in enumerate(next_steps, 1):
            tag = "" if step["fixable"] else " [manual]"
            lines.append(f"{i}. Check {step['check_id']} - {step['name']}{tag}: {step['action']}")
    else:
        lines.append("- None. This space is fully optimized.")
    lines.append("")

    return "\n".join(lines)
