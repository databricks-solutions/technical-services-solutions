"""
AWS Workspace Deployment Checklist (verify-oriented customer report).

Demo / hackathon helper: maps checker output to a short feasibility + Q4 summary.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import click

from checkers.base import CheckReport, CheckStatus

DEPLOYMENT_REQUIREMENTS: Dict[str, List[str]] = {
    "Serverless": [],
    "Express": [],
    "Classic": ["s3_create", "network_create", "iam_create"],
    "BYOVPC": ["s3_create", "network_create", "iam_create"],
    "Isolated PL": ["s3_create", "network_create", "iam_create"],
    "Data Exfil": ["s3_create", "network_create", "iam_create"],
}

_CAP_LABELS = {
    "aws_admin": "AWS Admin Privilege (new account)",
    "aws_marketplace_subscription": "AWS Marketplace subscription Privilege",
    "s3_create": "AWS S3 creation privilege",
    "network_create": "AWS network components creation privilege",
    "iam_create": "AWS IAM creation privilege",
    "dbx_account_admin": "Databricks Account Admin (existing account)",
}

_REMEDIATION = {
    "aws_admin": (
        "Missing AWS Admin–level readiness (S3 create, IAM create role, network checks, and valid credentials):",
        "Ensure the principal can manage S3, VPC/networking, and IAM resources required for a customer-managed VPC workspace.",
    ),
    "aws_marketplace_subscription": (
        "Missing AWS Marketplace subscription Privilege:",
        "Ensure the deployment principal can subscribe to Databricks via AWS Marketplace.",
    ),
    "s3_create": (
        "Missing AWS S3 creation privilege:",
        "Principal must be able to create and configure S3 buckets used for workspace root storage.",
    ),
    "network_create": (
        "Missing AWS network components creation privilege:",
        "Principal must be able to create/manage VPC, subnets, route tables, and security groups.",
    ),
    "iam_create": (
        "Missing AWS IAM creation privilege:",
        "Principal must be able to create/attach IAM roles and policies required by Databricks.",
    ),
    "dbx_account_admin": (
        "Missing Databricks Account Admin (cross-account) readiness:",
        "Principal must be able to configure the cross-account IAM trust and related EC2 permissions Databricks uses for clusters.",
    ),
}


def _result_matches_s3_create(name: str) -> bool:
    n = name.strip()
    return "s3:CreateBucket" in n


def _result_matches_iam_create(name: str) -> bool:
    n = name.strip()
    return "iam:CreateRole" in n


def _storage_category(report: CheckReport) -> Optional[Any]:
    for cat in report.categories:
        if "STORAGE" in cat.name.upper():
            return cat
    return None


def _s3_create_clearly_passed(report: CheckReport) -> bool:
    """True only if every s3:CreateBucket line in STORAGE is OK."""
    cat = _storage_category(report)
    if not cat:
        return False
    found = False
    for r in cat.results:
        if _result_matches_s3_create(r.name):
            found = True
            if r.status != CheckStatus.OK:
                return False
    return found


def _iam_create_clearly_passed(report: CheckReport) -> bool:
    """True if any iam:CreateRole line in the report is clearly OK."""
    for cat in report.categories:
        for r in cat.results:
            if _result_matches_iam_create(r.name) and r.status == CheckStatus.OK:
                return True
    return False


def _credentials_ok(report: CheckReport) -> bool:
    for cat in report.categories:
        if "CREDENTIAL" not in cat.name.upper():
            continue
        for r in cat.results:
            if r.status == CheckStatus.NOT_OK and "AWS SDK" not in r.name:
                return False
    return True


def _marketplace_passed(checker: Any) -> bool:
    try:
        if not getattr(checker, "_can_simulate", False):
            return False
        row = checker._simulate_actions(["aws-marketplace:ViewSubscriptions"])
        status, _ = row.get("aws-marketplace:ViewSubscriptions", ("error", ""))
        return status == "allowed"
    except Exception:
        return False


def build_aws_results_dict_from_report(report: CheckReport, checker: Any) -> Dict[str, Dict[str, bool]]:
    """
    Map CheckReport + AWSChecker into synthetic *_check keys for derive_capabilities_from_aws_results.

    Mappings (conservative — passed only when clearly OK or area flags are True):
    - s3_permissions_check: all s3:CreateBucket results in STORAGE category are OK
    - iam_permissions_check: any iam:CreateRole result is OK
    - network_permissions_check: checker._check_results_by_area['network']
    - databricks_account_admin_check: checker._check_results_by_area['cross_account']
    - marketplace_check: IAM simulation allows aws-marketplace:ViewSubscriptions (if simulation enabled)
    - aws_admin_check: credentials OK plus granular S3 create, IAM create role, and network area OK
    """
    areas = getattr(checker, "_check_results_by_area", {}) or {}
    s3_passed = _s3_create_clearly_passed(report)
    iam_passed = _iam_create_clearly_passed(report)
    net_passed = bool(areas.get("network", False))
    cross_passed = bool(areas.get("cross_account", False))
    mkt_passed = _marketplace_passed(checker)
    creds = _credentials_ok(report)

    # AWS admin (new account): AWS-plane create/describe signals without requiring Databricks cross-account.
    admin_passed = creds and s3_passed and iam_passed and net_passed

    return {
        "aws_admin_check": {"passed": admin_passed},
        "marketplace_check": {"passed": mkt_passed},
        "s3_permissions_check": {"passed": s3_passed},
        "network_permissions_check": {"passed": net_passed},
        "iam_permissions_check": {"passed": iam_passed},
        "databricks_account_admin_check": {"passed": cross_passed},
    }


def derive_capabilities_from_aws_results(aws_results: Dict[str, Dict[str, bool]]) -> Dict[str, bool]:
    caps = {
        "aws_admin": False,
        "aws_marketplace_subscription": False,
        "s3_create": False,
        "network_create": False,
        "iam_create": False,
        "dbx_account_admin": False,
    }
    if aws_results.get("aws_admin_check", {}).get("passed"):
        caps["aws_admin"] = True
    if aws_results.get("marketplace_check", {}).get("passed"):
        caps["aws_marketplace_subscription"] = True
    if aws_results.get("s3_permissions_check", {}).get("passed"):
        caps["s3_create"] = True
    if aws_results.get("network_permissions_check", {}).get("passed"):
        caps["network_create"] = True
    if aws_results.get("iam_permissions_check", {}).get("passed"):
        caps["iam_create"] = True
    if aws_results.get("databricks_account_admin_check", {}).get("passed"):
        caps["dbx_account_admin"] = True
    return caps


def compute_deployment_status(capabilities: Dict[str, bool]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for deploy_type, required in DEPLOYMENT_REQUIREMENTS.items():
        missing = [cap for cap in required if not capabilities.get(cap, False)]
        out[deploy_type] = {"ready": len(missing) == 0, "missing": missing}
    return out


def render_checklist_aws_output(
    capabilities: Dict[str, bool],
    deployment_status: Dict[str, Dict[str, Any]],
    region: str,
) -> str:
    lines: List[str] = []
    lines.append(f"AWS Workspace Deployment Feasibility (verify-only, region {region})")
    lines.append("")

    for dtype, meta in deployment_status.items():
        if meta["ready"]:
            lines.append(f"- {dtype}: READY")
        else:
            miss = ", ".join(meta["missing"])
            lines.append(f"- {dtype}: BLOCKED – missing: {miss}")

    lines.append("")
    lines.append("## Q4 – Customer Team Privileges (AWS)")
    lines.append("")

    for key in (
        "aws_admin",
        "aws_marketplace_subscription",
        "s3_create",
        "network_create",
        "iam_create",
        "dbx_account_admin",
    ):
        yn = "YES" if capabilities.get(key) else "NO"
        lines.append(f"* {_CAP_LABELS[key]}: {yn}")

    lines.append("")
    lines.append("## Remediation Summary")
    lines.append("")

    missing_any = [k for k, v in capabilities.items() if not v]
    if not missing_any:
        lines.append("All core privileges are present. No remediation required.")
    else:
        for cap in missing_any:
            title, body = _REMEDIATION[cap]
            lines.append(f"- {title}")
            lines.append(f"  {body}")
            lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    click.echo(text)
    return text
