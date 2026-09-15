"""Unit tests for Azure checker logic that doesn't require live credentials.

Guards a regression found running against a real subscription: recent
azure-mgmt-resource builds no longer ship `SubscriptionClient`, which used to
raise ImportError and fail the ENTIRE Azure run ("Azure SDK NOT OK", all areas
skipped). The checker must degrade to validating the subscription via the
resource client instead.
"""

import pytest

from checkers.azure import AzureChecker
from checkers.base import CheckCategory, CheckResult, CheckStatus


class _FakeResourceGroups:
    def list(self):
        return iter([])  # empty but iterable -> a successful read call


class _FakeResourceClient:
    resource_groups = _FakeResourceGroups()


def test_credentials_fall_back_when_subscription_client_unavailable(monkeypatch):
    c = AzureChecker(region="eastus", subscription_id="sub-123")
    # Simulate an SDK build with no SubscriptionClient, and a working resource client.
    monkeypatch.setattr(c, "_get_subscription_client", lambda: None)
    monkeypatch.setattr(c, "_get_resource_client", lambda: _FakeResourceClient())

    cat = c.check_credentials()
    by_name = {r.name: r for r in cat.results}

    # The run must NOT report the SDK as missing...
    assert not any(r.name == "Azure SDK" and r.status == CheckStatus.NOT_OK
                   for r in cat.results)
    # ...and must confirm credentials + the subscription id via the fallback.
    assert by_name["Azure Credentials"].status == CheckStatus.OK
    assert by_name["Subscription ID"].status == CheckStatus.OK
    assert by_name["Subscription ID"].message == "sub-123"


def test_credentials_fallback_reports_not_ok_when_subscription_unreachable(monkeypatch):
    c = AzureChecker(region="eastus", subscription_id="sub-123")

    class _BoomGroups:
        def list(self):
            raise PermissionError("AuthorizationFailed")

    class _BoomClient:
        resource_groups = _BoomGroups()

    monkeypatch.setattr(c, "_get_subscription_client", lambda: None)
    monkeypatch.setattr(c, "_get_resource_client", lambda: _BoomClient())

    cat = c.check_credentials()
    assert any(r.name == "Subscription Access" and r.status == CheckStatus.NOT_OK
               for r in cat.results)


def test_run_all_checks_verify_only_builds_compatibility_matrix(monkeypatch):
    # M11: run_all_checks was only exercised via check_credentials. This drives
    # the orchestration itself (verify-only): credentials pass, create-dependent
    # areas become NOT_TESTED, and a DEPLOYMENT COMPATIBILITY matrix is produced.
    c = AzureChecker(region="eastus", subscription_id="sub-123", verify_only=True)

    ok_cat = CheckCategory(name="CREDENTIALS")
    ok_cat.add_result(CheckResult(name="Azure Credentials",
                                  status=CheckStatus.OK, message="ok"))
    monkeypatch.setattr(c, "check_credentials", lambda: ok_cat)
    monkeypatch.setattr(c, "check_resource_providers",
                        lambda: CheckCategory(name="RESOURCE PROVIDERS"))
    monkeypatch.setattr(c, "_get_resource_client", lambda: object())
    monkeypatch.setattr(c, "_run_verify_only_checks", lambda rc: None)
    monkeypatch.setattr(c, "check_databricks_permissions",
                        lambda: CheckCategory(name="DATABRICKS WORKSPACE PERMISSIONS"))
    monkeypatch.setattr(c, "check_quotas",
                        lambda: CheckCategory(name="QUOTAS & LIMITS"))

    report = c.run_all_checks()

    names = [cat.name for cat in report.categories]
    assert any("DEPLOYMENT COMPATIBILITY" in n for n in names)
    # verify-only cannot confirm create/write, so create-dependent areas are
    # NOT_TESTED (never "supported").
    assert c._check_results_by_area.get("network") == "NOT_TESTED"


def test_azure_network_create_denied_is_not_ok(monkeypatch):
    # A denied NSG create must be NOT_OK (a blocked deploy permission). Exercises
    # the Azure resource-create path (audit: was ~0% covered).
    c = AzureChecker(region="eastus", subscription_id="sub-123")

    class _DenyNSG:
        def begin_create_or_update(self, *a, **k):
            raise Exception("AuthorizationFailed: client does not have authorization "
                            "to perform action 'Microsoft.Network/networkSecurityGroups/write'")

    class _NetClient:
        network_security_groups = _DenyNSG()

    monkeypatch.setattr(c, "_get_network_client", lambda: _NetClient())
    by_name = {r.name.strip(): r for r in c._test_network_permissions(test_rg="rg-test")}
    assert by_name["Microsoft.Network/networkSecurityGroups/write"].status == CheckStatus.NOT_OK


def test_azure_cleanup_failures_surface_as_not_ok(monkeypatch):
    # Azure parity with AWS review H1: a failed Resource-Group delete must be
    # surfaced as a NOT_OK "Leaked resource", never swallowed silently.
    c = AzureChecker(region="eastus", subscription_id="sub-123")

    ok_cat = CheckCategory(name="CREDENTIALS")
    ok_cat.add_result(CheckResult(name="Azure Credentials",
                                  status=CheckStatus.OK, message="ok"))
    monkeypatch.setattr(c, "check_credentials", lambda: ok_cat)
    monkeypatch.setattr(c, "check_resource_providers",
                        lambda: CheckCategory(name="RESOURCE PROVIDERS"))
    monkeypatch.setattr(c, "_get_resource_client", lambda: object())
    monkeypatch.setattr(c, "check_databricks_permissions",
                        lambda: CheckCategory(name="DATABRICKS WORKSPACE PERMISSIONS"))
    monkeypatch.setattr(c, "check_quotas", lambda: CheckCategory(name="QUOTAS & LIMITS"))
    monkeypatch.setattr(c, "_compute_deployment_compatibility",
                        lambda: CheckCategory(name="DEPLOYMENT COMPATIBILITY"))

    def _raiser():
        raise RuntimeError("RG delete throttled")

    def _fake_full(resource_client, test_rg):
        c._cleanup_tasks.append((_raiser, test_rg))  # a delete that will FAIL
        return True  # rg_created

    monkeypatch.setattr(c, "_run_full_checks", _fake_full)

    report = c.run_all_checks()
    leaked = [r for cat in report.categories for r in cat.results
              if "Leaked resource" in r.name]
    assert leaked, "a failed RG delete must be surfaced, not swallowed"
    assert all(r.status == CheckStatus.NOT_OK for r in leaked)
