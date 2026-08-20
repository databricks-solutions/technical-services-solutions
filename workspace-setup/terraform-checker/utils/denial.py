"""
Access-denial detection — dependency-free on purpose.

Kept separate from error_handlers (which imports checkers.base) so the cloud
checkers can import it without creating a circular import.

The original checkers only matched "AccessDenied" / "is not authorized", which
silently let SCP / permission-boundary denials, *Exception-suffixed codes, and
explicit-deny wording fall through to a non-blocking WARNING — so a real denial
was reported as "passed". This module centralizes comprehensive detection.
"""

# Substrings (lower-cased) that indicate an access/authorization denial across
# AWS, Azure and GCP.
_DENIAL_MARKERS = (
    # AWS
    "accessdenied",
    "access denied",
    "unauthorizedoperation",
    "not authorized to perform",
    "is not authorized",
    "explicit deny",
    "with an explicit deny",
    "service control policy",
    "you are not authorized",
    "forbidden",
    # Azure
    "authorizationfailed",
    "does not have authorization",
    "insufficient privileges",
    "linkedauthorizationfailed",
    # GCP
    "permission denied",
    "permissiondenied",
    "caller does not have permission",
    "the caller does not have permission",
    "iam permission",
    "403",
)


def is_access_denied(error: object) -> bool:
    """
    Return True if the error text looks like an access/authorization denial.

    Accepts an Exception or a string. Matching is case-insensitive and covers
    AWS, Azure and GCP denial phrasings. Use this instead of ad-hoc substring
    checks so denials are never misclassified as benign warnings (fail-open).
    """
    text = (error if isinstance(error, str) else str(error)).lower()
    return any(marker in text for marker in _DENIAL_MARKERS)


# Errors that block a real `terraform apply` even though they aren't pure
# authorization denials: org/account policies that disallow the operation, and
# quota exhaustion. Throttling is transient (retryable), NOT deploy-blocking.
_DEPLOY_BLOCKING_MARKERS = (
    "requestdisallowedbypolicy",
    "requestdisallowedbyazurepolicy",
    "disallowed by policy",
    "scp",                       # AWS service control policy
    "service control policy",
    "quotaexceeded",
    "limitexceeded",
    "quota exceeded",
    "resourcequotaexceeded",
)


def is_deploy_blocking(error: object) -> bool:
    """True if the error would block a real deployment: an access denial, an
    org/account policy that disallows the op, or quota exhaustion. Use for
    *create* probes so a policy/quota block is reported NOT_OK, not a soft
    warning. (Transient throttling is intentionally excluded.)"""
    if is_access_denied(error):
        return True
    text = (error if isinstance(error, str) else str(error)).lower()
    return any(marker in text for marker in _DEPLOY_BLOCKING_MARKERS)


def is_throttling(error: object) -> bool:
    """True for transient rate-limit/throttling errors (retryable)."""
    text = (error if isinstance(error, str) else str(error)).lower()
    return any(m in text for m in (
        "throttl", "rate exceeded", "requestlimitexceeded",
        "toomanyrequests", "429", "toomanyrequestsexception",
    ))
