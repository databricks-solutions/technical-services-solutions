"""Regression tests for the Polly review fixes.

Covers behaviors the review (M11) called out as untested: cleanup-failure
reporting, the area_state scoring guard, the report verdict for NOT-VERIFIED
runs, defensive delete, and GCP resilient batching.
"""

import pytest

from checkers.aws import AWSChecker
from checkers.gcp import GCPChecker
from checkers.base import CheckCategory, CheckReport, CheckResult, CheckStatus
from reporters.markdown_reporter import MarkdownReporter


# --------------------------------------------------------------------------- #
# M9 — decorative rows must not inflate the scoring OK count / area_state
# --------------------------------------------------------------------------- #

def test_decorative_only_area_is_not_tested_not_pass():
    cat = CheckCategory(name="STORAGE")
    cat.add_result(CheckResult(name="Test Method", status=CheckStatus.OK, message="creating…"))
    cat.add_result(CheckResult(name="── S3 Bucket Operations ──", status=CheckStatus.OK))
    cat.add_result(CheckResult(name="  📦 Creating test bucket", status=CheckStatus.OK, message="dbxprecheck-x"))
    cat.add_result(CheckResult(name="  s3:CreateBucket", status=CheckStatus.WARNING, message="unverified"))
    # The only OK rows are decorative → nothing was actually verified.
    assert cat.area_state == "NOT_TESTED"


def test_real_ok_row_alongside_decorative_is_pass():
    cat = CheckCategory(name="STORAGE")
    cat.add_result(CheckResult(name="  📦 Creating test bucket", status=CheckStatus.OK, message="x"))
    cat.add_result(CheckResult(name="  s3:CreateBucket", status=CheckStatus.OK, message="VERIFIED"))
    assert cat.area_state == "PASS"


def test_explicit_decorative_flag_is_excluded_from_scoring():
    cat = CheckCategory(name="X")
    cat.add_result(CheckResult(name="  looks-real", status=CheckStatus.OK, decorative=True))
    cat.add_result(CheckResult(name="  real:Check", status=CheckStatus.WARNING))
    assert cat.area_state == "NOT_TESTED"


# --------------------------------------------------------------------------- #
# H1 — cleanup failures are returned/reported; inline deletes unregister
# --------------------------------------------------------------------------- #

def test_cleanup_returns_failures_and_clears_queue():
    c = AWSChecker(region="us-east-1")
    ran = []
    c._cleanup_tasks = [
        (lambda: ran.append("ok"), "ok-res"),
        (lambda: (_ for _ in ()).throw(RuntimeError("boom")), "bad-res"),
    ]
    failures = c._cleanup_test_resources()
    assert ran == ["ok"]
    assert [name for name, _err in failures] == ["bad-res"]
    assert c._cleanup_tasks == []


def test_unregister_cleanup_drops_only_that_resource():
    c = AWSChecker(region="us-east-1")
    c._cleanup_tasks = [(lambda: None, "a"), (lambda: None, "b")]
    c._unregister_cleanup("a")
    assert [name for _fn, name in c._cleanup_tasks] == ["b"]


# --------------------------------------------------------------------------- #
# M2 — _safe_delete tolerates "not found", re-raises real errors
# --------------------------------------------------------------------------- #

def test_safe_delete_swallows_not_found():
    def delete():
        raise Exception("NoSuchEntity: already gone")
    AWSChecker._safe_delete(delete, ["NoSuchEntity"])  # must not raise


def test_safe_delete_reraises_real_errors():
    def delete():
        raise Exception("AccessDenied: nope")
    with pytest.raises(Exception):
        AWSChecker._safe_delete(delete, ["NoSuchEntity"])


# --------------------------------------------------------------------------- #
# H12 — verdict is "verification incomplete" for a NOT-VERIFIED run
# --------------------------------------------------------------------------- #

def test_verdict_not_verified_is_incomplete_not_ready_to_deploy():
    report = CheckReport(cloud="AWS", region="us-east-1")
    compat = CheckCategory(name="DEPLOYMENT COMPATIBILITY")
    compat.add_result(CheckResult(
        name="Standard", status=CheckStatus.WARNING,
        message="NOT VERIFIED - could not confirm: network (IAM simulation unavailable)",
    ))
    report.add_category(compat)
    _icon, headline, _summary = MarkdownReporter()._verdict(report)
    assert "Verification incomplete" in headline
    assert "Ready to deploy" not in headline


def test_verdict_clean_run_is_ready_to_deploy():
    report = CheckReport(cloud="AWS", region="us-east-1")
    compat = CheckCategory(name="DEPLOYMENT COMPATIBILITY")
    compat.add_result(CheckResult(name="Standard", status=CheckStatus.OK, message="SUPPORTED"))
    report.add_category(compat)
    _icon, headline, _summary = MarkdownReporter()._verdict(report)
    assert headline == "Ready to deploy"


# --------------------------------------------------------------------------- #
# M7 — GCP resilient batching isolates an invalid permission
# --------------------------------------------------------------------------- #

class _FakeReq:
    def __init__(self, result=None, error=None):
        self._result, self._error = result, error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class _FakeProjects:
    def __init__(self, valid):
        self.valid = set(valid)

    def testIamPermissions(self, resource=None, body=None):
        perms = body["permissions"]
        if "bad.perm" in perms:
            return _FakeReq(error=Exception(
                "HttpError 400: Permission bad.perm is not valid (INVALID_ARGUMENT)"))
        return _FakeReq(result={"permissions": [p for p in perms if p in self.valid]})


class _FakeRm:
    def __init__(self, valid):
        self._projects = _FakeProjects(valid)

    def projects(self):
        return self._projects


def test_resilient_batching_isolates_invalid_permission():
    c = GCPChecker(region="us-central1", project_id="p")
    granted, invalid = set(), set()
    c._test_permissions_resilient(
        _FakeRm({"a.b.c", "d.e.f"}), ["a.b.c", "bad.perm", "d.e.f"], granted, invalid,
    )
    assert granted == {"a.b.c", "d.e.f"}
    assert invalid == {"bad.perm"}


def test_resilient_batching_reraises_non_400_errors():
    class _AuthReq:
        def execute(self):
            raise Exception("HttpError 403: caller does not have permission")

    class _AuthProjects:
        def testIamPermissions(self, resource=None, body=None):
            return _AuthReq()

    class _AuthRm:
        def projects(self):
            return _AuthProjects()

    c = GCPChecker(region="us-central1", project_id="p")
    with pytest.raises(Exception):
        c._test_permissions_resilient(_AuthRm(), ["a.b.c", "d.e.f"], set(), set())
