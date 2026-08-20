"""Unit tests for Azure checker logic that doesn't require live credentials.

Guards a regression found running against a real subscription: recent
azure-mgmt-resource builds no longer ship `SubscriptionClient`, which used to
raise ImportError and fail the ENTIRE Azure run ("Azure SDK NOT OK", all areas
skipped). The checker must degrade to validating the subscription via the
resource client instead.
"""

import pytest

from checkers.azure import AzureChecker
from checkers.base import CheckStatus


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
