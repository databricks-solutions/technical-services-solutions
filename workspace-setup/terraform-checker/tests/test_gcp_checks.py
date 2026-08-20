"""Unit tests for GCP checker logic that does NOT require live GCP credentials.

These tests exercise the pure error-classification and permission-evaluation
logic plus the check methods, driving them with fake clients/errors. No live
GCP / network call is ever made.

They guard the audit-finding fixes (§3.1-§3.8):
  * full required set drives testIamPermissions, batched <=100/call
  * ANY missing deploy-blocking perm -> NOT_OK (not a fractional WARNING)
  * actAs/getAccessToken called out as the #1 deploy blocker
  * PSC/DNS not silently OK when in scope and missing
  * 'can list' != 'can use/create'
  * check_apis probes per-API instead of skip-and-pass
  * HttpError.resp.status (int) drives classification; accessNotConfigured
    (enable API) separated from permission-denied (grant role)
"""

import pytest

from checkers.gcp import GCPChecker
from checkers.base import CheckStatus


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, status, reason="error"):
        self.status = status
        self.reason = reason


class _FakeHttpError(Exception):
    """Mimics googleapiclient.errors.HttpError enough for classification."""
    def __init__(self, status, reason="error"):
        super().__init__(f"<HttpError {status}: {reason}>")
        self.resp = _FakeResp(status, reason)
        self.status_code = status
        self._reason = reason

    def _get_reason(self):
        return self._reason


class _FakeTestIamPermissions:
    """Records the batches it was asked about; returns a fixed granted set."""
    def __init__(self, granted, raise_error=None):
        self._granted = set(granted)
        self._raise = raise_error
        self.batches = []

    def __call__(self, resource=None, body=None):
        self.batches.append(list(body["permissions"]))
        outer = self

        class _Req:
            def execute(self_inner):
                if outer._raise is not None:
                    raise outer._raise
                asked = body["permissions"]
                return {"permissions": [p for p in asked if p in outer._granted]}
        return _Req()


class _FakeProjects:
    def __init__(self, tip):
        self._tip = tip

    def testIamPermissions(self, resource=None, body=None):
        return self._tip(resource=resource, body=body)


class _FakeRmClient:
    def __init__(self, tip):
        self._projects = _FakeProjects(tip)

    def projects(self):
        return self._projects


def _checker(**kw):
    return GCPChecker(region="us-central1", project_id="proj-123", **kw)


def _all_granted(scopes):
    perms, _ = GCPChecker._build_permission_request(scopes)
    return set(perms)


# --------------------------------------------------------------------------- #
# Pure helpers: error classification
# --------------------------------------------------------------------------- #

def test_http_status_prefers_resp_status_int():
    assert GCPChecker._http_status(_FakeHttpError(403)) == 403
    assert GCPChecker._http_status(_FakeHttpError(404)) == 404
    assert GCPChecker._http_status(Exception("no status here")) is None


def test_classify_permission_denied_via_status():
    e = _FakeHttpError(403, "The caller does not have permission")
    assert GCPChecker._classify_api_error(e) == "permission_denied"


def test_classify_api_disabled_separated_from_permission_denied():
    # accessNotConfigured surfaces as 403 but must be classified as enable-API,
    # NOT grant-role.
    e = _FakeHttpError(
        403,
        "Compute Engine API has not been used in project 1 before or it is disabled. "
        "accessNotConfigured",
    )
    assert GCPChecker._classify_api_error(e) == "api_disabled"


def test_classify_not_found():
    assert GCPChecker._classify_api_error(_FakeHttpError(404, "not_found")) == "not_found"


def test_error_reason_full_not_truncated():
    long = "x" * 200
    assert GCPChecker._error_reason(_FakeHttpError(403, long)) == long
    assert len(GCPChecker._error_reason(_FakeHttpError(403, long))) == 200


# --------------------------------------------------------------------------- #
# Pure helpers: batching + dedup + scope
# --------------------------------------------------------------------------- #

def test_permission_request_is_deduped_and_scoped():
    base = GCPChecker._scopes_in_effect(psc=False, dns=False, cmek=False)
    full = GCPChecker._scopes_in_effect(psc=True, dns=True, cmek=True)
    base_perms, _ = GCPChecker._build_permission_request(base)
    full_perms, _ = GCPChecker._build_permission_request(full)
    # full superset of base, both deduped (sorted unique)
    assert set(base_perms) <= set(full_perms)
    assert len(base_perms) == len(set(base_perms))
    # PSC/DNS perms only appear when those scopes are active
    assert "dns.managedZones.create" not in base_perms
    assert "dns.managedZones.create" in full_perms
    assert "compute.forwardingRules.create" in full_perms


def test_batched_respects_100_limit():
    perms = [f"svc.perm{i}" for i in range(250)]
    batches = GCPChecker._batched(perms)
    assert [len(b) for b in batches] == [100, 100, 50]
    assert all(len(b) <= 100 for b in batches)


def test_batched_empty_yields_single_empty_batch():
    assert GCPChecker._batched([]) == [[]]


# --------------------------------------------------------------------------- #
# Pure helpers: permission evaluation (the core fail-closed logic)
# --------------------------------------------------------------------------- #

def test_any_missing_blocking_is_not_ok_not_fractional_warning():
    scopes = GCPChecker._scopes_in_effect(psc=False, dns=False, cmek=False)
    granted = _all_granted(scopes) - {"iam.serviceAccounts.actAs"}
    res = GCPChecker._evaluate_permissions(granted, scopes)
    # Only ONE perm missing of many -> still NOT_OK because it's deploy-blocking.
    assert res["iam"]["status"] == CheckStatus.NOT_OK
    assert "iam.serviceAccounts.actAs" in res["iam"]["missing_blocking"]


def test_missing_non_blocking_is_warning():
    scopes = GCPChecker._scopes_in_effect(psc=False, dns=False, cmek=False)
    # compute.subnetworks.useExternalIp is required but NOT deploy-blocking.
    granted = _all_granted(scopes) - {"compute.subnetworks.useExternalIp"}
    res = GCPChecker._evaluate_permissions(granted, scopes)
    assert res["network"]["status"] == CheckStatus.WARNING


def test_all_granted_is_ok():
    scopes = GCPChecker._scopes_in_effect(psc=True, dns=True, cmek=True)
    res = GCPChecker._evaluate_permissions(_all_granted(scopes), scopes)
    assert all(v["status"] == CheckStatus.OK for v in res.values())


def test_out_of_scope_areas_not_evaluated():
    scopes = GCPChecker._scopes_in_effect(psc=False, dns=False, cmek=False)
    res = GCPChecker._evaluate_permissions(set(), scopes)
    assert "psc" not in res and "dns" not in res and "kms" not in res
    assert "project" in res and "network" in res


# --------------------------------------------------------------------------- #
# check_iam_permissions wiring (with fake testIamPermissions)
# --------------------------------------------------------------------------- #

def test_iam_check_batches_and_flags_blocking(monkeypatch):
    c = _checker()
    scopes = GCPChecker._scopes_in_effect(psc=True, dns=True, cmek=True)
    granted = _all_granted(scopes) - {"storage.buckets.create"}
    tip = _FakeTestIamPermissions(granted)
    monkeypatch.setattr(c, "_get_resource_manager_client", lambda: _FakeRmClient(tip))

    cat = c.check_iam_permissions()
    # batched <=100/call
    assert all(len(b) <= 100 for b in tip.batches)
    by_status = {r.name: r.status for r in cat.results}
    storage = next(r for r in cat.results if r.name.startswith("STORAGE"))
    assert storage.status == CheckStatus.NOT_OK
    assert "storage.buckets.create" in (storage.message or "")
    assert storage.remediation


def test_iam_check_cannot_test_is_warning_not_pass(monkeypatch):
    c = _checker()
    tip = _FakeTestIamPermissions(set(), raise_error=_FakeHttpError(403, "denied"))
    monkeypatch.setattr(c, "_get_resource_manager_client", lambda: _FakeRmClient(tip))
    cat = c.check_iam_permissions()
    # Must surface as WARNING/assumed, never silently OK.
    assert cat.results[0].status == CheckStatus.WARNING
    assert cat.results[0].assumed is True
    assert cat.results[0].remediation


# --------------------------------------------------------------------------- #
# check_impersonation (the #1 deploy blocker)
# --------------------------------------------------------------------------- #

def test_impersonation_missing_actas_is_not_ok(monkeypatch):
    c = _checker()
    # getAccessToken granted but actAs missing
    tip = _FakeTestIamPermissions({"iam.serviceAccounts.getAccessToken",
                                   "iam.serviceAccounts.getOpenIdToken"})
    monkeypatch.setattr(c, "_get_resource_manager_client", lambda: _FakeRmClient(tip))
    cat = c.check_impersonation()
    actas = next(r for r in cat.results if r.name == "iam.serviceAccounts.actAs")
    assert actas.status == CheckStatus.NOT_OK
    assert actas.remediation and "serviceAccountUser" in actas.remediation


def test_impersonation_all_granted_ok(monkeypatch):
    c = _checker()
    tip = _FakeTestIamPermissions({"iam.serviceAccounts.actAs",
                                   "iam.serviceAccounts.getAccessToken",
                                   "iam.serviceAccounts.getOpenIdToken"})
    monkeypatch.setattr(c, "_get_resource_manager_client", lambda: _FakeRmClient(tip))
    cat = c.check_impersonation()
    assert all(r.status == CheckStatus.OK for r in cat.results)


# --------------------------------------------------------------------------- #
# PSC/DNS: not silently OK when in scope and missing; SKIPPED when out of scope
# --------------------------------------------------------------------------- #

def test_psc_missing_is_blocking_when_in_scope(monkeypatch):
    c = _checker()
    c.check_psc, c.check_dns, c.check_cmek = True, False, False
    tip = _FakeTestIamPermissions(set())  # nothing granted
    monkeypatch.setattr(c, "_get_resource_manager_client", lambda: _FakeRmClient(tip))
    cat = c.check_private_connectivity()
    assert any(r.status == CheckStatus.NOT_OK for r in cat.results)


def test_psc_skipped_when_out_of_scope():
    c = _checker()
    c.check_psc, c.check_dns = False, False
    cat = c.check_private_connectivity()
    assert all(r.status == CheckStatus.SKIPPED for r in cat.results)


def test_network_create_use_not_list(monkeypatch):
    # Granting only list-style perms must NOT make the network area OK.
    c = _checker()
    tip = _FakeTestIamPermissions({"compute.networks.get",
                                   "compute.subnetworks.get",
                                   "compute.firewalls.get"})
    monkeypatch.setattr(c, "_get_resource_manager_client", lambda: _FakeRmClient(tip))
    cat = c.check_network()
    assert any(r.status == CheckStatus.NOT_OK for r in cat.results)


# --------------------------------------------------------------------------- #
# check_apis fallback / per-API
# --------------------------------------------------------------------------- #

class _FakeServices:
    def __init__(self, enabled=None, list_error=None, get_error=None):
        self._enabled = enabled
        self._list_error = list_error
        self._get_error = get_error

    def list(self, parent=None, filter=None):
        outer = self

        class _Req:
            def execute(self_inner):
                if outer._list_error is not None:
                    raise outer._list_error
                return {"services": [
                    {"config": {"name": n}} for n in (outer._enabled or [])
                ]}
        return _Req()

    def list_next(self, request, response):
        return None

    def get(self, name=None):
        outer = self
        api = name.split("/services/")[-1]

        class _Req:
            def execute(self_inner):
                if outer._get_error is not None:
                    raise outer._get_error
                state = "ENABLED" if api in (outer._enabled or []) else "DISABLED"
                return {"state": state}
        return _Req()


class _FakeSuClient:
    def __init__(self, services):
        self._services = services

    def services(self):
        return self._services


def test_apis_bulk_list_marks_missing_not_ok(monkeypatch):
    c = _checker()
    c.check_psc, c.check_dns, c.check_cmek = False, False, False
    svc = _FakeServices(enabled=["compute.googleapis.com"])  # most missing
    monkeypatch.setattr(c, "_get_service_usage_client", lambda: _FakeSuClient(svc))
    cat = c.check_apis()
    compute = next(r for r in cat.results if "compute.googleapis.com" in r.name)
    iam = next(r for r in cat.results if "iam.googleapis.com" in r.name)
    assert compute.status == CheckStatus.OK
    assert iam.status == CheckStatus.NOT_OK
    assert iam.remediation and "gcloud services enable" in iam.remediation


def test_apis_falls_back_to_per_api_probe_when_list_fails(monkeypatch):
    c = _checker()
    c.check_psc, c.check_dns, c.check_cmek = False, False, False
    svc = _FakeServices(enabled=["iam.googleapis.com"],
                        list_error=_FakeHttpError(403, "denied"))
    monkeypatch.setattr(c, "_get_service_usage_client", lambda: _FakeSuClient(svc))
    cat = c.check_apis()
    # No result should be skipped/silently-passed: each API resolved by probe.
    assert all(r.status != CheckStatus.SKIPPED for r in cat.results)
    iam = next(r for r in cat.results if "iam.googleapis.com" in r.name)
    assert iam.status == CheckStatus.OK
    compute = next(r for r in cat.results if "compute.googleapis.com" in r.name)
    assert compute.status == CheckStatus.NOT_OK


def test_apis_probe_unverifiable_is_warning_not_pass(monkeypatch):
    c = _checker()
    c.check_psc, c.check_dns, c.check_cmek = False, False, False
    # list fails AND per-API get fails with a non-disabled error -> UNVERIFIED
    svc = _FakeServices(list_error=_FakeHttpError(500, "server error"),
                        get_error=_FakeHttpError(500, "server error"))
    monkeypatch.setattr(c, "_get_service_usage_client", lambda: _FakeSuClient(svc))
    cat = c.check_apis()
    assert all(r.status == CheckStatus.WARNING and r.assumed for r in cat.results)
    assert all("UNVERIFIED" in (r.message or "") for r in cat.results)


# --------------------------------------------------------------------------- #
# Scope note / interface
# --------------------------------------------------------------------------- #

def test_scope_note_is_informational_and_states_beta_readonly():
    cat = _checker().check_scope_note()
    assert len(cat.results) == 1
    r = cat.results[0]
    assert r.status == CheckStatus.SKIPPED
    msg = r.message or ""
    assert "BETA" in msg and "READ-ONLY" in msg and "PARTIAL" in msg


def test_interface_preserved():
    c = GCPChecker(region=None, project_id="p", credentials_file=None)
    assert c.cloud_name == "GCP"
    assert callable(c.check_credentials)
    assert callable(c.run_all_checks)
