"""The customer-facing text report must be English (no leftover Portuguese) and
must format the problems / quota boxes. Guards the audit finding that the
'PROBLEMS FOUND' box headers had shipped in Portuguese, and covers txt_reporter
(which was ~6% covered)."""

from checkers.base import CheckReport, CheckCategory, CheckResult, CheckStatus
from reporters.txt_reporter import TxtReporter


def _report_with_problems():
    rep = CheckReport(cloud="AWS", region="us-east-1")
    perm = CheckCategory(name="CROSS-ACCOUNT ROLE")
    perm.add_result(CheckResult(
        name="  iam:CreateRole", status=CheckStatus.NOT_OK,
        message="DENIED: not authorized to perform iam:CreateRole"))
    rep.add_category(perm)
    quota = CheckCategory(name="QUOTAS & LIMITS")
    quota.add_result(CheckResult(
        name="  vCPUs", status=CheckStatus.NOT_OK,
        message="QUOTA exceeded: 0 of 100 available"))
    rep.add_category(quota)
    return rep


def test_txt_report_headers_are_english():
    out = TxtReporter().generate(_report_with_problems())
    assert "MISSING PERMISSIONS" in out
    assert "WHAT TO DO" in out
    assert "QUOTA LIMITS REACHED" in out


def test_txt_report_has_no_portuguese():
    out = TxtReporter().generate(_report_with_problems())
    for pt in ("PERMISSÕES", "FALTANDO", "O QUE FAZER", "LIMITES DE QUOTA", "ATINGIDOS"):
        assert pt not in out, f"leftover Portuguese in customer report: {pt!r}"


def test_txt_report_clean_run_has_no_problem_box():
    rep = CheckReport(cloud="AWS", region="us-east-1")
    cat = CheckCategory(name="STORAGE CONFIGURATION")
    cat.add_result(CheckResult(name="  s3:CreateBucket",
                               status=CheckStatus.OK, message="VERIFIED"))
    rep.add_category(cat)
    out = TxtReporter().generate(rep)
    assert "PROBLEMS FOUND" not in out
    assert "MISSING PERMISSIONS" not in out
