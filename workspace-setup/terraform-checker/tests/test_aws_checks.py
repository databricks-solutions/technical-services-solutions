"""Unit tests for AWS checker logic that doesn't require live credentials.

Guards two defects found by running the checker against a real account:
  - Defect 2: fake placeholder ids (i-test12345 / vol-test12345) produced
    InvalidInstanceID / InvalidVolume errors that were misread as WARNINGs
    even though the permission was granted.
  - Defect 1: there was no KMS check and no statement of what is NOT validated,
    so a FULL run green-lit a deploy that needs always-on CMK.
"""

import pytest

from checkers.aws import AWSChecker
from checkers.base import CheckCategory, CheckResult, CheckStatus


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for _test_dryrun."""
    def __init__(self, code, message="error"):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


def _checker():
    return AWSChecker(region="us-east-1")


@pytest.mark.parametrize("code", [
    "InvalidInstanceID.NotFound",
    "InvalidVolume.NotFound",
])
def test_resource_not_found_counts_as_permission_ok(code):
    # AWS evaluated the request, authorization PASSED, and only then found the
    # placeholder resource missing — so the permission is genuinely granted.
    def boom():
        raise _FakeClientError(code)
    status, _msg, _assumed = _checker()._test_dryrun("ec2:TerminateInstances", boom)
    assert status == CheckStatus.OK


@pytest.mark.parametrize("code", [
    "InvalidInstanceID.Malformed",
    "InvalidParameterValue",
    "MalformedAMIID",
])
def test_parameter_validation_errors_are_unverified(code):
    # Rejected BEFORE authorization was evaluated (a malformed/invalid parameter)
    # — this proves nothing about the permission, so it must be WARNING
    # (unverified), never OK. Reporting it OK produced a false PASS (review H3).
    def boom():
        raise _FakeClientError(code)
    status, _msg, assumed = _checker()._test_dryrun("ec2:RunInstances", boom)
    assert status == CheckStatus.WARNING
    # H3: an unverified (parameter-validation) result must be flagged assumed, so
    # a mixed area drops to NOT_TESTED instead of reading a false PASS.
    assert assumed is True


@pytest.mark.parametrize("code", ["UnauthorizedOperation", "AccessDenied"])
def test_real_denial_still_not_ok(code):
    def boom():
        raise _FakeClientError(code, "You are not authorized")
    status, _msg, _assumed = _checker()._test_dryrun("ec2:RunInstances", boom)
    assert status == CheckStatus.NOT_OK


def test_dryrun_success_is_ok():
    def boom():
        raise _FakeClientError("DryRunOperation", "would have succeeded")
    status, _msg, _assumed = _checker()._test_dryrun("ec2:CreateVpc", boom)
    assert status == CheckStatus.OK


def test_kms_check_warns_when_simulation_unavailable():
    c = _checker()
    c._can_simulate = False
    cat = c.check_kms()
    statuses = [r.status for r in cat.results]
    # Must surface (not silently pass) and must NOT be a hard failure.
    assert CheckStatus.WARNING in statuses
    assert CheckStatus.NOT_OK not in statuses
    joined = " ".join(r.message or "" for r in cat.results)
    assert "kms:CreateKey" in joined  # tells the user exactly what's needed


def test_account_api_scope_note_is_explicit():
    cat = _checker().check_account_api_scope_note()
    assert all(r.status == CheckStatus.SKIPPED for r in cat.results)
    text = " ".join((r.message or "") for r in cat.results)
    assert "databricks_mws_" in text
    assert "account-admin token" in text


def test_verify_only_probe_creates_nothing_and_is_honest():
    c = AWSChecker(region="us-east-1", verify_only=True)
    c._can_simulate = False
    res = c._test_s3_bucket_permissions()  # would normally create a bucket
    msgs = " ".join(r.message or "" for r in res)
    assert "No resources created" in msgs
    # Without simulation it must say it can't fully verify (not a false OK)
    assert any(r.status == CheckStatus.WARNING for r in res)


def test_sg_egress_covers_port():
    cov = AWSChecker._egress_covers_port
    assert cov([{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443}], 443) is True
    assert cov([{"IpProtocol": "tcp", "FromPort": 8443, "ToPort": 8451}], 8445) is True
    assert cov([{"IpProtocol": "-1"}], 6666) is True            # all-traffic
    assert cov([{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443}], 3306) is False
    assert cov([], 443) is False


def test_sg_has_self_all_traffic():
    has = AWSChecker._has_self_all_traffic
    self_all = [{"IpProtocol": "tcp", "FromPort": 0, "ToPort": 65535,
                 "UserIdGroupPairs": [{"GroupId": "sg-x"}]}]
    assert has(self_all, "sg-x") is True
    assert has(self_all, "sg-other") is False           # different SG
    narrow = [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
               "UserIdGroupPairs": [{"GroupId": "sg-x"}]}]
    assert has(narrow, "sg-x") is False                 # not all-traffic
    allproto = [{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": "sg-x"}]}]
    assert has(allproto, "sg-x") is True


def test_compatibility_matrix_reports_all_modes():
    c = _checker()
    c._check_results_by_area = {
        "storage": "PASS", "network": "PASS", "cross_account": "PASS",
        "privatelink": "FAIL", "unity_catalog": "PASS",
    }
    cat = c._compute_deployment_compatibility()
    by_name = {r.name.strip(): r for r in cat.results}
    assert by_name["Standard"].status == CheckStatus.OK
    assert by_name["Unity Catalog"].status == CheckStatus.OK
    # privatelink FAILED -> PrivateLink and Full are NOT SUPPORTED (blocker)
    assert by_name["PrivateLink"].status == CheckStatus.NOT_OK
    assert by_name["Full"].status == CheckStatus.NOT_OK
    assert "VPC endpoints" in (by_name["PrivateLink"].message or "")


def test_compatibility_matrix_not_tested_is_not_supported():
    # The core false-green fix: an unverified area must NOT read as SUPPORTED.
    c = _checker()
    c._check_results_by_area = {
        "storage": "PASS", "network": "PASS", "cross_account": "PASS",
        "privatelink": "PASS", "unity_catalog": "NOT_TESTED",
    }
    by_name = {r.name.strip(): r for r in c._compute_deployment_compatibility().results}
    assert by_name["Standard"].status == CheckStatus.OK          # its areas all PASS
    assert by_name["Unity Catalog"].status == CheckStatus.WARNING  # NOT VERIFIED, not SUPPORTED
    assert "NOT VERIFIED" in (by_name["Unity Catalog"].message or "")


def test_compatibility_matrix_review_distinct_from_not_verified():
    # A verified area with an actionable advisory (REVIEW) must read as REVIEW,
    # NOT as NOT VERIFIED (which is reserved for areas we couldn't confirm).
    c = _checker()
    c._check_results_by_area = {
        "storage": "PASS", "network": "REVIEW", "cross_account": "PASS",
        "privatelink": "PASS", "unity_catalog": "PASS",
    }
    by_name = {r.name.strip(): r for r in c._compute_deployment_compatibility().results}
    # Every mode needs network, so all land in REVIEW (warning, but not a blocker).
    for mode in ("Standard", "PrivateLink", "Unity Catalog", "Full"):
        assert by_name[mode].status == CheckStatus.WARNING
        assert by_name[mode].message.startswith("REVIEW")
        assert "network" in by_name[mode].message
        assert "NOT VERIFIED" not in by_name[mode].message


def test_compatibility_matrix_not_tested_outranks_review():
    # If an area is genuinely unconfirmed, the mode is NOT VERIFIED even when
    # another required area only has advisories — never overstate confidence.
    c = _checker()
    c._check_results_by_area = {
        "storage": "REVIEW", "network": "NOT_TESTED", "cross_account": "PASS",
    }
    standard = next(r for r in c._compute_deployment_compatibility().results
                    if r.name.strip() == "Standard")
    assert standard.status == CheckStatus.WARNING
    assert "NOT VERIFIED" in standard.message


def test_area_state_distinguishes_review_assumed_and_clean():
    base_ok = CheckResult(name="ok", status=CheckStatus.OK, message="verified")

    # Clean: verified, no advisories -> PASS
    clean = CheckCategory(name="x", results=[base_ok])
    assert clean.area_state == "PASS"

    # Actionable advisory (WARNING + remediation), verified -> REVIEW
    review = CheckCategory(name="x", results=[
        base_ok,
        CheckResult(name="adv", status=CheckStatus.WARNING,
                    message="subnet too small", remediation="use /24"),
    ])
    assert review.area_state == "REVIEW"

    # Assumed/guessed value -> NOT_TESTED (couldn't truly confirm), even with an OK
    assumed = CheckCategory(name="x", results=[
        base_ok,
        CheckResult(name="kms", status=CheckStatus.WARNING,
                    message="could not verify", remediation="grant kms:*", assumed=True),
    ])
    assert assumed.area_state == "NOT_TESTED"

    # Benign warning (no remediation) does NOT disqualify a PASS
    benign = CheckCategory(name="x", results=[
        base_ok,
        CheckResult(name="info", status=CheckStatus.WARNING, message="fyi"),
    ])
    assert benign.area_state == "PASS"


def test_h3_param_validation_assumed_drops_mixed_area_to_not_tested():
    # H3: a mixed area (an OK read + a create probe that only reached parameter
    # validation) never actually verified the create permission. Flagging it
    # assumed must drop the whole area to NOT_TESTED, not read a false PASS.
    describe_ok = CheckResult(name="  ec2:DescribeVpcEndpoints",
                              status=CheckStatus.OK, message="Allowed")
    create_unverified = CheckResult(
        name="  ec2:CreateVpcEndpoint (S3 Gateway)",
        status=CheckStatus.WARNING,
        message="Unverified — request rejected at parameter validation",
        assumed=True,
    )
    mixed = CheckCategory(name="privatelink",
                          results=[describe_ok, create_unverified])
    assert mixed.area_state == "NOT_TESTED"

    # Sanity: the SAME rows without the assumed flag would have read PASS —
    # exactly the false-green that H3 closes.
    not_flagged = CheckResult(
        name="  ec2:CreateVpcEndpoint (S3 Gateway)",
        status=CheckStatus.WARNING, message="Unverified", assumed=False,
    )
    assert CheckCategory(name="privatelink",
                         results=[describe_ok, not_flagged]).area_state == "PASS"


def test_skip_cleanup_does_not_invoke_cleanup_tasks():
    # --skip-cleanup (review H10): registered temp resources are intentionally
    # left in place — the cleanup callables must NOT run.
    c = AWSChecker(region="us-east-1", skip_cleanup=True)
    called = []
    c._cleanup_tasks = [(lambda: called.append(1), "temp-bucket")]
    assert c._cleanup_test_resources() == []
    assert called == []


def test_cleanup_runs_when_not_skipped():
    c = AWSChecker(region="us-east-1")  # skip_cleanup defaults to False
    called = []
    c._cleanup_tasks = [(lambda: called.append(1), "temp-bucket")]
    assert c._cleanup_test_resources() == []   # deletion succeeded, no failures
    assert called == [1]                        # cleanup callable actually ran


# --- Create-path error handling (audit: these paths were barely covered) ------

def test_s3_create_denied_is_not_ok(monkeypatch):
    # A denied CreateBucket must be NOT_OK (a blocked deploy permission), never a
    # soft warning that could read as PASS. Exercises the real create path.
    c = AWSChecker(region="us-east-1")
    c._account_id = "123456789012"

    class _DenyS3:
        def create_bucket(self, **kw):
            raise _FakeClientError("AccessDenied",
                                   "User is not authorized to perform: s3:CreateBucket")

    monkeypatch.setattr(c, "_get_client", lambda service: _DenyS3())
    by_name = {r.name.strip(): r for r in c._test_s3_bucket_permissions()}
    assert by_name["s3:CreateBucket"].status == CheckStatus.NOT_OK
    assert "DENIED" in by_name["s3:CreateBucket"].message


def test_s3_ambiguous_create_error_registers_cleanup(monkeypatch):
    # An ambiguous (non-denial, non-already-owned) error might mean the bucket
    # WAS created server-side, so a not-found-tolerant cleanup must be registered
    # (review M2) — never orphan — and it reports WARNING, not a false OK.
    c = AWSChecker(region="us-east-1")
    c._account_id = "123456789012"

    class _WeirdS3:
        def create_bucket(self, **kw):
            raise _FakeClientError("InternalError", "something ambiguous happened")

    monkeypatch.setattr(c, "_get_client", lambda service: _WeirdS3())
    by_name = {r.name.strip(): r for r in c._test_s3_bucket_permissions()}
    assert by_name["s3:CreateBucket"].status == CheckStatus.WARNING
    assert len(c._cleanup_tasks) == 1  # registered so a server-side create can't leak


def test_iam_role_create_denied_is_not_ok(monkeypatch):
    # A denied CreateRole must be NOT_OK. Exercises the IAM role create path.
    c = AWSChecker(region="us-east-1")
    c._account_id = "123456789012"

    class _DenyIam:
        def create_role(self, **kw):
            raise _FakeClientError("AccessDenied",
                                   "not authorized to perform: iam:CreateRole")

    monkeypatch.setattr(c, "_get_client", lambda service: _DenyIam())
    by_name = {r.name.strip(): r for r in c._test_iam_role_permissions()}
    assert by_name["iam:CreateRole"].status == CheckStatus.NOT_OK
    assert "DENIED" in by_name["iam:CreateRole"].message
