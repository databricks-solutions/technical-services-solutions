"""Tests for the customer-friendly Markdown reporter."""

import pytest

from checkers.base import (
    CheckReport, CheckCategory, CheckResult, CheckStatus,
)
from reporters import MarkdownReporter
from reporters.markdown_reporter import MarkdownReporter as DirectMD


def _report_with(*results, cloud="AWS", region="us-east-1"):
    cat = CheckCategory(name="STEP 1: STORAGE")
    for r in results:
        cat.add_result(r)
    report = CheckReport(cloud=cloud, region=region)
    report.account_info = "Account: 123456789"
    report.add_category(cat)
    return report


def test_passing_report_says_ready():
    report = _report_with(
        CheckResult(name="s3:CreateBucket", status=CheckStatus.OK, message="✓ CREATED"),
    )
    md = MarkdownReporter().generate(report)
    assert "Ready to deploy" in md
    assert "✅" in md
    assert md.startswith("# Databricks Deployment Pre-Check")


def test_failing_report_lists_blockers_and_fix():
    report = _report_with(
        CheckResult(
            name="📦 s3:PutBucketPolicy",
            status=CheckStatus.NOT_OK,
            message="DENIED: not authorized to perform s3:PutBucketPolicy",
            remediation="Grant s3:PutBucketPolicy on the root bucket.",
            doc_link="https://docs.databricks.com/aws/storage",
        ),
    )
    md = MarkdownReporter().generate(report)
    assert "Action required" in md
    assert "What you need to fix" in md
    assert "Grant s3:PutBucketPolicy" in md          # uses remediation
    assert "https://docs.databricks.com/aws/storage" in md
    # decorative icon and DENIED: prefix stripped from prose
    assert "📦" not in md.split("Full check detail")[0]
    assert "DENIED:" not in md.split("Full check detail")[0]


def test_failure_without_remediation_falls_back_to_generic():
    report = _report_with(
        CheckResult(name="iam:CreateRole", status=CheckStatus.NOT_OK, message="DENIED"),
        cloud="Azure",
    )
    md = MarkdownReporter().generate(report)
    assert "Contributor" in md  # azure generic fix guidance


def test_warning_report_is_proceed_with_review():
    report = _report_with(
        CheckResult(name="vCPU quota", status=CheckStatus.WARNING, message="QUOTA: limit assumed"),
    )
    md = MarkdownReporter().generate(report)
    assert "with a few things to review" in md
    assert "Worth reviewing" in md


def test_detail_table_present_and_counts_summary():
    report = _report_with(
        CheckResult(name="a", status=CheckStatus.OK),
        CheckResult(name="b", status=CheckStatus.NOT_OK, message="DENIED"),
    )
    md = MarkdownReporter().generate(report)
    assert "Full check detail" in md
    assert "| ✅ 1 | ⚠️ 0 | ❌ 1 | ⏭️ 0 |" in md


def test_multi_cloud_report():
    r1 = _report_with(CheckResult(name="x", status=CheckStatus.OK), cloud="AWS")
    r2 = _report_with(CheckResult(name="y", status=CheckStatus.NOT_OK, message="DENIED"), cloud="GCP")
    md = MarkdownReporter().generate_all_clouds([r1, r2])
    assert "Multi-Cloud Report" in md
    assert "blocker(s) across 2 cloud(s)" in md


def test_warnings_split_actionable_vs_notes():
    # A warning WITH remediation is a real review item; one WITHOUT is a note.
    report = _report_with(
        CheckResult(name="KMS permissions", status=CheckStatus.WARNING,
                    message="Could not verify KMS",
                    remediation="Grant kms:CreateKey to the principal."),
        CheckResult(name="Scope", status=CheckStatus.WARNING,
                    message="No --vpc-id given: counting subnets account-wide"),
    )
    md = MarkdownReporter().generate(report)
    assert "Worth reviewing" in md
    assert "Notes (no action needed)" in md
    review = md.split("Notes (no action needed)")[0]
    notes = md.split("Notes (no action needed)")[1].split("Next steps")[0]
    assert "Grant kms:CreateKey" in review
    # Informational note must NOT get a scary generic "ask your admin" fix
    assert "Scope" in notes
    assert "administrator" not in notes


def test_compatibility_and_not_validated_are_prominent_sections():
    cat = CheckCategory(name="DEPLOYMENT COMPATIBILITY")
    cat.add_result(CheckResult(name="Full", status=CheckStatus.WARNING,
                               message="NOT VERIFIED - could not confirm: network",
                               remediation="Re-run without --verify-only."))
    nv = CheckCategory(name="NOT VALIDATED BY THIS PRE-CHECK (read this)")
    nv.add_result(CheckResult(name="Account registration", status=CheckStatus.SKIPPED,
                              message="databricks_mws_* need an account token"))
    report = CheckReport(cloud="AWS", region="us-east-1")
    report.add_category(cat)
    report.add_category(nv)
    md = MarkdownReporter().generate(report)
    assert "## Deployment compatibility" in md
    assert "## ⛔ Not validated by this pre-check" in md
    # matrix items must NOT be scattered into the generic "Worth reviewing" bucket
    before_detail = md.split("Full check detail")[0]
    assert before_detail.count("Re-run without --verify-only.") <= 1
    # the special categories are not duplicated inside the collapsed detail
    assert "DEPLOYMENT COMPATIBILITY" not in md.split("Full check detail")[1]


def test_export_path_is_same_class():
    assert MarkdownReporter is DirectMD
