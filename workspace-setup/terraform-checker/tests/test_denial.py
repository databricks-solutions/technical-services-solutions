"""Tests for comprehensive access-denial detection (fail-open guard)."""

import pytest

from utils.denial import is_access_denied
from utils.error_handlers import is_access_denied as is_access_denied_reexport


# Real-world denial messages that the OLD narrow check
# (`"AccessDenied" in s or "is not authorized" in s`) would MISS, letting a
# genuine denial be reported as a benign WARNING.
DENIALS = [
    "An error occurred (UnauthorizedOperation) when calling the RunInstances operation",
    "User: arn:aws:iam::1:user/x is not authorized to perform: ec2:CreateVpc",
    "AccessDeniedException: explicit deny in a service control policy",
    "with an explicit deny in a service control policy",
    "API error: 403 Forbidden",
    "AuthorizationFailed: The client does not have authorization to perform action",
    "LinkedAuthorizationFailed: linked auth failed",
    "Insufficient privileges to complete the operation",
    "Permission denied on resource project foo",
    "The caller does not have permission",
    "PERMISSION_DENIED: Missing iam permission compute.subnetworks.use",
]

NON_DENIALS = [
    "ThrottlingException: Rate exceeded",
    "RequestLimitExceeded: too many requests",
    "Could not connect to the endpoint URL",
    "ResourceNotFoundException: bucket does not exist",
    "BucketAlreadyOwnedByYou",
    "ServiceUnavailable: try again later",
    "",
]


@pytest.mark.parametrize("msg", DENIALS)
def test_detects_denials(msg):
    assert is_access_denied(msg) is True


@pytest.mark.parametrize("msg", NON_DENIALS)
def test_ignores_non_denials(msg):
    # Must NOT flip transient/not-found errors into denials (avoids false alarms)
    assert is_access_denied(msg) is False


def test_accepts_exception_objects():
    assert is_access_denied(Exception("AccessDenied")) is True
    assert is_access_denied(RuntimeError("ThrottlingException")) is False


def test_case_insensitive():
    assert is_access_denied("ACCESSDENIED") is True
    assert is_access_denied("accessdenied") is True


def test_reexport_is_same_callable():
    assert is_access_denied_reexport is is_access_denied


def test_is_deploy_blocking():
    from utils.denial import is_deploy_blocking
    assert is_deploy_blocking("AccessDenied") is True
    assert is_deploy_blocking("RequestDisallowedByPolicy: blocked by initiative") is True
    assert is_deploy_blocking("QuotaExceeded: regional cores") is True
    assert is_deploy_blocking("ThrottlingException: rate exceeded") is False
    assert is_deploy_blocking("connection reset") is False


def test_is_throttling():
    from utils.denial import is_throttling
    assert is_throttling("RequestLimitExceeded") is True
    assert is_throttling("429 Too Many Requests") is True
    assert is_throttling("AccessDenied") is False
