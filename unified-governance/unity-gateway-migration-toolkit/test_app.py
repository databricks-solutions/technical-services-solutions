"""Security tests for the Unity Gateway Migration app backend (FastAPI TestClient; Databricks clients are mocked).

Run: uv run --with pytest --with "databricks-sdk>=0.158.0" --with requests --with fastapi --with httpx python -m pytest -q test_app.py
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import DatabricksError
from fastapi.testclient import TestClient

from app.backend import main

OP_TOKEN, VIEWER_TOKEN = "tok-op", "tok-viewer"
OP_EMAIL, VIEWER_EMAIL = "op@example.com", "viewer@example.com"
TOKENS = {OP_TOKEN: OP_EMAIL, VIEWER_TOKEN: VIEWER_EMAIL}
SCAN = "11111111-2222-3333-4444-555555555555"
DRY = "66666666-7777-8888-9999-000000000000"
ME_CALLS = {"n": 0}


class FakeWC:
    """Stands in for WorkspaceClient(host=..., token=...): current_user.me() resolves the token like Databricks does."""

    def __init__(self, host=None, token=None, auth_type=None):
        self._token = token

    @property
    def current_user(self):
        return self

    def me(self):
        ME_CALLS["n"] += 1
        if self._token not in TOKENS:
            raise RuntimeError("invalid token")
        return SimpleNamespace(user_name=TOKENS[self._token])


def fake_sdk():
    sdk = MagicMock()
    sdk.config = SimpleNamespace(host="https://ws.example.com")
    sdk.jobs.run_now.return_value = SimpleNamespace(run_id=555)
    sdk.jobs.list_runs.side_effect = lambda **kw: iter([])
    return sdk


def make_query(store):
    def fake(request, sql, params=None):
        p = params or {}
        if "UNION ALL" in sql:  # job ownership lookup: who requested runs with this job run id
            return [{"requested_by": r.get("requested_by")} for r in store["scans"] + store["applies"]
                    if r.get("job_run_id") == p.get("j")]
        if "ug_migration_scan_items" in sql:
            return store["items"]
        if "ug_migration_scans" in sql:
            return [r for r in store["scans"] if r["run_id"] == p.get("r")]
        if "ug_migration_applies" in sql:
            return [r for r in store["applies"] if r["apply_id"] == p.get("a")]
        return []
    return fake


def now_ts(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(main, "IN_APP", True)
    monkeypatch.setattr(main, "LOCAL_DEV", False)
    monkeypatch.setattr(main, "OPERATORS", {OP_EMAIL})
    monkeypatch.setattr(main, "SECRET_SCHEMAS", {"cat.sec"})
    monkeypatch.setattr(main, "ALLOW_SECRET_READ", False)
    monkeypatch.setattr(main, "MAX_SCAN_AGE_DAYS", 14)
    monkeypatch.setattr(main, "RESULTS_SCHEMA", "cat.sch")
    monkeypatch.setattr(main, "WAREHOUSE_ID", "wh")
    monkeypatch.setattr(main, "JOBS", {"snapshot": "11", "scan": "22", "apply": "33"})
    monkeypatch.setattr(main, "EXPORT_ROW_LIMIT", 200_000)
    monkeypatch.setattr(main, "_identities", {})
    monkeypatch.setattr(main, "_owners", {})
    monkeypatch.setattr(main, "WorkspaceClient", FakeWC)
    sdk = fake_sdk()
    monkeypatch.setattr(main, "_sp", sdk)
    store = {
        "scans": [{"run_id": SCAN, "status": "SUCCEEDED", "ts": now_ts(1), "job_run_id": "900",
                   "requested_by": VIEWER_EMAIL}],
        "applies": [{"apply_id": DRY, "mode": "dry_run", "status": "SUCCEEDED", "job_run_id": "777",
                     "scan_run_id": SCAN}],
        "items": [],
    }
    monkeypatch.setattr(main, "query", make_query(store))
    ME_CALLS["n"] = 0
    return SimpleNamespace(sdk=sdk, store=store, client=TestClient(main.app))


def as_user(token, email=None):
    h = {"x-forwarded-access-token": token}
    if email is not None:
        h["x-forwarded-email"] = email
    return h


def job_params(**over):
    base = {"scan_run_id": SCAN, "endpoints": "ep-a", "target_catalog": "ai_gateway", "target_schema": "migrated",
            "uc_secret_map": "", "allow_secret_read": "false", "grants": "false", "ack_guardrails": "false"}
    base.update(over)
    return [SimpleNamespace(name=k, value=v, default=None) for k, v in base.items()]


EXECUTE_BODY = {"mode": "execute", "scan_run_id": SCAN, "endpoints": ["ep-a"], "target_catalog": "ai_gateway",
                "target_schema": "migrated", "confirm": "EXECUTE", "dry_run_id": DRY}
DRY_BODY = {"mode": "dry_run", "scan_run_id": SCAN, "endpoints": ["ep-a"], "target_catalog": "ai_gateway",
            "target_schema": "migrated"}


# ---------------------------------------------------------------------------
# Identity and operators
# ---------------------------------------------------------------------------


def test_outside_app_without_local_dev_is_default_deny(env, monkeypatch):
    monkeypatch.setattr(main, "IN_APP", False)
    monkeypatch.setattr(main, "LOCAL_DEV", False)
    me = env.client.get("/api/whoami")
    assert me.status_code == 200 and me.json()["operator"] is False and me.json()["email"] == ""
    assert env.client.post("/api/account/snapshot", json={}).status_code == 401
    assert env.sdk.jobs.run_now.call_count == 0


def test_local_dev_flag_allows_operator_actions(env, monkeypatch):
    monkeypatch.setattr(main, "IN_APP", False)
    monkeypatch.setattr(main, "LOCAL_DEV", True)
    assert env.client.get("/api/whoami").json()["operator"] is True
    assert env.client.post("/api/account/snapshot", json={}).status_code == 200
    assert env.sdk.jobs.run_now.call_count == 1


def test_forged_email_header_without_token_is_rejected(env):
    r = env.client.post("/api/account/snapshot", json={}, headers={"x-forwarded-email": OP_EMAIL})
    assert r.status_code == 401
    assert env.sdk.jobs.run_now.call_count == 0


def test_operator_identity_comes_from_the_token(env):
    r = env.client.post("/api/account/snapshot", json={}, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 200
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert params["requested_by"] == OP_EMAIL


def test_viewer_is_not_an_operator(env):
    assert env.client.post("/api/account/snapshot", json={}, headers=as_user(VIEWER_TOKEN)).status_code == 403


def test_email_header_that_does_not_match_the_token_fails_closed(env):
    # A viewer's token with an operator's email header must not act as the operator.
    r = env.client.post("/api/account/snapshot", json={}, headers=as_user(VIEWER_TOKEN, OP_EMAIL))
    assert r.status_code == 403
    assert env.client.get("/api/whoami", headers=as_user(VIEWER_TOKEN, OP_EMAIL)).status_code == 403
    assert env.sdk.jobs.run_now.call_count == 0


def test_unverifiable_token_fails_closed(env):
    assert env.client.post("/api/account/snapshot", json={}, headers=as_user("bogus", OP_EMAIL)).status_code == 401
    assert env.client.get("/api/whoami", headers=as_user("bogus")).status_code == 401


def test_identity_is_cached_per_token(env):
    for _ in range(3):
        env.client.get("/api/whoami", headers=as_user(OP_TOKEN, OP_EMAIL))
    assert ME_CALLS["n"] == 1


# ---------------------------------------------------------------------------
# CSRF hardening
# ---------------------------------------------------------------------------


def test_post_must_be_json(env):
    r = env.client.post("/api/account/snapshot", content="{}", headers={**as_user(OP_TOKEN, OP_EMAIL),
                                                                        "content-type": "text/plain"})
    assert r.status_code == 415
    assert env.sdk.jobs.run_now.call_count == 0


def test_cross_site_post_is_blocked(env):
    r = env.client.post("/api/account/snapshot", json={}, headers={**as_user(OP_TOKEN, OP_EMAIL),
                                                                   "sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert env.sdk.jobs.run_now.call_count == 0


# ---------------------------------------------------------------------------
# Jobs: fail closed, and messages only for owners and operators
# ---------------------------------------------------------------------------


def test_active_run_check_fails_closed(env):
    def broken(**kw):
        raise DatabricksError("boom")
    env.sdk.jobs.list_runs.side_effect = broken
    r = env.client.post("/api/account/snapshot", json={}, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 503
    assert env.sdk.jobs.run_now.call_count == 0


def _run(job_id="22"):
    return SimpleNamespace(job_id=int(job_id), start_time=1, end_time=None, run_page_url="https://jobs.example/run",
                           state=SimpleNamespace(life_cycle_state=SimpleNamespace(value="RUNNING"), result_state=None,
                                                 state_message="reads table cat.sec.secret"))


def test_job_status_hides_message_and_link_from_other_viewers(env):
    env.sdk.jobs.get_run.return_value = _run()
    r = env.client.get("/api/jobs/999", headers=as_user(VIEWER_TOKEN, VIEWER_EMAIL)).json()
    assert r["life_cycle"] == "RUNNING" and "message" not in r and "url" not in r


def test_job_status_shows_message_to_the_run_owner(env):
    env.sdk.jobs.get_run.return_value = _run()
    env.store["scans"].append({"run_id": "other", "status": "RUNNING", "job_run_id": "999", "requested_by": VIEWER_EMAIL})
    r = env.client.get("/api/jobs/999", headers=as_user(VIEWER_TOKEN, VIEWER_EMAIL)).json()
    assert r["message"] and r["url"]


def test_job_status_shows_everything_to_operators(env):
    env.sdk.jobs.get_run.return_value = _run()
    r = env.client.get("/api/jobs/999", headers=as_user(OP_TOKEN, OP_EMAIL)).json()
    assert r["url"] and r["message"]


def test_job_status_hides_message_when_ownership_lookup_fails(env, monkeypatch):
    env.sdk.jobs.get_run.return_value = _run()

    def boom(request, sql, params=None):
        raise main.HTTPException(502, "warehouse down")
    monkeypatch.setattr(main, "query", boom)
    r = env.client.get("/api/jobs/999", headers=as_user(VIEWER_TOKEN, VIEWER_EMAIL)).json()
    assert "message" not in r


# ---------------------------------------------------------------------------
# Apply: secrets, dry run gating, stale scans, guardrails, exports
# ---------------------------------------------------------------------------


def test_secret_map_outside_allowed_schemas_is_rejected(env):
    body = {**DRY_BODY, "uc_secret_map": {"scope/key": "secrets/cat.other.name"}}
    r = env.client.post("/api/applies", json=body, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 400 and "allowed" in r.json()["detail"]


def test_secret_map_inside_allowed_schema_is_passed_on(env):
    body = {**DRY_BODY, "uc_secret_map": {"scope/key": "secrets/cat.sec.name"}}
    r = env.client.post("/api/applies", json=body, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 200
    assert json.loads(env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["uc_secret_map"]) == \
        {"scope/key": "secrets/cat.sec.name"}


def test_allow_secret_read_needs_install_flag(env, monkeypatch):
    body = {**DRY_BODY, "allow_secret_read": True}
    assert env.client.post("/api/applies", json=body, headers=as_user(OP_TOKEN, OP_EMAIL)).status_code == 400
    monkeypatch.setattr(main, "ALLOW_SECRET_READ", True)
    assert env.client.post("/api/applies", json=body, headers=as_user(OP_TOKEN, OP_EMAIL)).status_code == 200


def test_config_exposes_allowed_schemas_and_limits(env):
    cfg = env.client.get("/api/config").json()
    assert cfg["secret_schemas"] == ["cat.sec"] and cfg["allow_secret_read"] is False
    assert cfg["max_scan_age_days"] == 14


def test_execute_needs_a_dry_run_id(env):
    body = {k: v for k, v in EXECUTE_BODY.items() if k != "dry_run_id"}
    r = env.client.post("/api/applies", json=body, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 400 and "dry run" in r.json()["detail"]


def test_execute_follows_a_matching_dry_run(env):
    env.sdk.jobs.get_run.return_value = SimpleNamespace(job_parameters=job_params())
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 200
    assert env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["mode"] == "execute"


def test_execute_rejects_changed_options(env):
    env.sdk.jobs.get_run.return_value = SimpleNamespace(job_parameters=job_params())
    body = {**EXECUTE_BODY, "grants": True}
    r = env.client.post("/api/applies", json=body, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_execute_rejects_a_dry_run_that_did_not_succeed(env):
    env.store["applies"][0]["status"] = "FAILED"
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 409


def test_execute_rejects_a_dry_run_of_another_scan(env):
    env.store["applies"][0]["scan_run_id"] = "other-scan"
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 409


def test_stale_scan_is_rejected_unless_allowed(env):
    env.store["scans"][0]["ts"] = now_ts(30)
    assert env.client.post("/api/applies", json=DRY_BODY, headers=as_user(OP_TOKEN, OP_EMAIL)).status_code == 409
    body = {**DRY_BODY, "allow_stale": True}
    assert env.client.post("/api/applies", json=body, headers=as_user(OP_TOKEN, OP_EMAIL)).status_code == 200


def test_execute_needs_guardrail_acknowledgement(env):
    env.store["items"] = [{"payload": json.dumps({"legacy_endpoint": "ep-a",
                                                  "needs_human": ["guardrails: input safety: built-in"]})}]
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 400 and "guardrails" in r.json()["detail"]


def test_dry_run_fingerprint_depends_on_selection_and_options_only():
    a = {"scan_run_id": SCAN, "endpoints": "ep-a", "grants": "false", "unrelated": "x"}
    b = {"grants": "false", "endpoints": "ep-a", "scan_run_id": SCAN, "requested_by": "someone"}
    assert main.selection_fingerprint(a) == main.selection_fingerprint(b)
    assert main.selection_fingerprint(a) != main.selection_fingerprint({**a, "endpoints": "ep-b"})


def test_scan_export_marks_truncation(env, monkeypatch):
    item = {"payload": json.dumps({"legacy_endpoint": "ep-a"})}
    env.store["items"] = [item, item]
    monkeypatch.setattr(main, "EXPORT_ROW_LIMIT", 2)
    r = env.client.get(f"/api/scans/{SCAN}/export/plan", headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 200 and r.headers.get("x-truncated") == "true"
    monkeypatch.setattr(main, "EXPORT_ROW_LIMIT", 5)
    r = env.client.get(f"/api/scans/{SCAN}/export/plan", headers=as_user(OP_TOKEN, OP_EMAIL))
    assert "x-truncated" not in r.headers
