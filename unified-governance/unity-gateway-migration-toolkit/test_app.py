"""Security tests for the Unity Gateway Migration app backend (FastAPI TestClient; Databricks clients are mocked).

Run: uv run --with pytest --with "databricks-sdk>=0.158.0" --with requests --with fastapi --with httpx python -m pytest -q test_app.py
"""

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import DatabricksError, NotFound
from fastapi.testclient import TestClient

import ug_migration_planner as planner
import ug_migration_store as store
from app.backend import main

OP_TOKEN, VIEWER_TOKEN = "tok-op", "tok-viewer"
OP_EMAIL, VIEWER_EMAIL = "op@example.com", "viewer@example.com"
TOKENS = {OP_TOKEN: OP_EMAIL, VIEWER_TOKEN: VIEWER_EMAIL}
SCAN = "11111111-2222-3333-4444-555555555555"
DRY = "66666666-7777-8888-9999-000000000000"
DRY_OK = "cccccccc-1111-2222-3333-444444444444"
EXEC = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ROLLBACK = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
HOST = "https://ws.example.com"
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
    sdk.config = SimpleNamespace(host=HOST)
    sdk.jobs.run_now.return_value = SimpleNamespace(run_id=555)
    sdk.jobs.list_runs.side_effect = lambda **kw: iter([])
    return sdk


def make_query(store):
    """Answers the SQL the app sends, from the rows in the test's store (routed by the table each query reads)."""
    def fake(request, sql, params=None, **kw):
        p = params or {}
        if "UNION ALL" in sql:  # job ownership lookup: who requested runs with this job run id
            return [{"requested_by": r.get("requested_by")} for r in store["scans"] + store["applies"]
                    if r.get("job_run_id") == p.get("j")]
        if "ug_migration_scan_items" in sql:
            return store["items"]
        if "ug_migration_apply_items" in sql:
            return store["apply_items"]
        if "mode = 'rollback'" in sql:  # rows without a mode are rollbacks; the SQL filters on mode
            return [r for r in store["rollbacks"] if r.get("mode", "rollback") == "rollback"
                    and ("a" not in p or r["rollback_of"] == p["a"])]
        if "ug_migration_scans" in sql:
            return [r for r in store["scans"] if "r" not in p or r["run_id"] == p["r"]]
        if "ug_migration_applies" in sql and "dry_run_id = :dry_run_id" in sql:  # single use: an execute of this dry run
            return [{"apply_id": r["apply_id"]} for r in store["applies"]
                    if r.get("dry_run_id") == p["dry_run_id"] and r.get("mode") in ("execute", "rollback")]
        if "ug_migration_applies" in sql:
            return [r for r in store["applies"] if "a" not in p or r["apply_id"] == p["a"]]
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
    monkeypatch.setattr(main, "_admins", {})
    monkeypatch.setattr(main, "_operators", {"until": 0.0, "rows": [], "error": None})
    monkeypatch.setattr(main, "app_query", lambda sql, params=None, missing_ok=True: [])  # an empty operators table
    monkeypatch.setattr(main, "_job_identities", {})
    monkeypatch.setattr(main, "_owners", {})
    monkeypatch.setattr(main, "_started", {})
    monkeypatch.setattr(main, "WorkspaceClient", FakeWC)
    sdk = fake_sdk()
    monkeypatch.setattr(main, "_sp", sdk)
    store_rows = {
        "scans": [{"run_id": SCAN, "status": "SUCCEEDED", "ts": now_ts(1), "job_run_id": "900",
                   "requested_by": VIEWER_EMAIL, "workspace_url": HOST}],
        "applies": [{"apply_id": DRY, "mode": "dry_run", "started_at": now_ts(), "status": "SUCCEEDED", "job_run_id": "777",
                     "scan_run_id": SCAN}],
        "items": [], "apply_items": [], "rollbacks": [],
    }
    monkeypatch.setattr(main, "query", make_query(store_rows))
    ME_CALLS["n"] = 0
    return SimpleNamespace(sdk=sdk, store=store_rows, client=TestClient(main.app))


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
OP = as_user(OP_TOKEN, OP_EMAIL)


def stored_fingerprint(**over):
    """The fingerprint the dry-run job stores for DRY_BODY's selection (computed by the job-side function)."""
    params = {"scan_run_id": SCAN, "endpoints": "ep-a", "target_catalog": "ai_gateway", "target_schema": "migrated",
              "uc_secret_map": "", "allow_secret_read": "false", "grants": "false", "ack_guardrails": "false"}
    params.update(over)
    return store.selection_fingerprint(params)


def planner_scan_items(tmp_path, endpoints=None):
    """Scan item rows the way the scan job stores them: the planner's own plan CSV, read back by the store."""
    from test_planner import EXTERNAL, _ep
    rows, _ = planner.plan(endpoints or [_ep(EXTERNAL)], {}, {}, "ai_gateway", "migrated", traffic_known=False)
    path = tmp_path / "migration_plan.csv"
    planner._write_csv(str(path), [asdict(r) for r in rows])
    return [{"payload": json.dumps(r)} for r in store._csv(str(path))]


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
# Jobs: fail closed, messages only for owners and operators, and "already running" conflicts
# ---------------------------------------------------------------------------


def test_active_run_check_fails_closed(env):
    def broken(**kw):
        raise DatabricksError("boom")
    env.sdk.jobs.list_runs.side_effect = broken
    r = env.client.post("/api/account/snapshot", json={}, headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 503 and "already running" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def _active(run_id=42):
    env_runs = [SimpleNamespace(run_id=run_id, run_page_url=f"https://jobs.example/{run_id}")]
    return lambda **kw: iter(env_runs)


@pytest.mark.parametrize("path, body, text", [
    ("/api/account/snapshot", {}, "A snapshot is already running"),
    ("/api/scans", {"days": 30}, "A scan is already running"),
    ("/api/applies", DRY_BODY, "An apply run is already running"),
])
def test_conflict_names_the_active_job_run_and_its_link(env, path, body, text):
    env.sdk.jobs.list_runs.side_effect = _active(42)
    r = env.client.post(path, json=body, headers=OP)
    assert r.status_code == 409
    out = r.json()
    assert text in out["detail"] and "42" in out["detail"]
    assert out["job_run_id"] == "42" and out["url"] == "https://jobs.example/42"
    assert env.sdk.jobs.run_now.call_count == 0


def test_job_status_hides_message_and_link_from_other_viewers(env):
    env.sdk.jobs.get_run.return_value = _run()
    r = env.client.get("/api/jobs/999", headers=as_user(VIEWER_TOKEN, VIEWER_EMAIL)).json()
    assert r["life_cycle"] == "RUNNING" and "message" not in r and "url" not in r


def _run(job_id="22"):
    return SimpleNamespace(job_id=int(job_id), start_time=1, end_time=None, run_page_url="https://jobs.example/run",
                           state=SimpleNamespace(life_cycle_state=SimpleNamespace(value="RUNNING"), result_state=None,
                                                 state_message="reads table cat.sec.secret"))


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

    def boom(request, sql, params=None, **kw):
        raise main.HTTPException(502, "warehouse down")
    monkeypatch.setattr(main, "query", boom)
    r = env.client.get("/api/jobs/999", headers=as_user(VIEWER_TOKEN, VIEWER_EMAIL)).json()
    assert "message" not in r


# ---------------------------------------------------------------------------
# Scans and apply runs that are starting, unknown, or finished (the 202 / 404 contract)
# ---------------------------------------------------------------------------


def _job_state(life_cycle):
    return SimpleNamespace(state=SimpleNamespace(life_cycle_state=SimpleNamespace(value=life_cycle), result_state=None))


def test_started_apply_is_202_until_its_row_is_stored(env):
    r = env.client.post("/api/applies", json=DRY_BODY, headers=OP)
    apply_id = r.json()["apply_id"]
    env.sdk.jobs.get_run.return_value = _job_state("PENDING")
    pending = env.client.get(f"/api/applies/{apply_id}")
    assert pending.status_code == 202
    assert pending.json()["meta"] == {"apply_id": apply_id, "status": "STARTING", "job_run_id": "555"}
    # The job ended without writing a row: the run is not found any more.
    env.sdk.jobs.get_run.return_value = _job_state("INTERNAL_ERROR")
    gone = env.client.get(f"/api/applies/{apply_id}")
    assert gone.status_code == 404 and gone.json()["detail"] == "not found"


def test_started_scan_is_202_until_its_row_is_stored(env):
    run_id = env.client.post("/api/scans", json={"days": 30}, headers=OP).json()["run_id"]
    env.sdk.jobs.get_run.return_value = _job_state("RUNNING")
    assert env.client.get(f"/api/scans/{run_id}").status_code == 202


def test_unknown_scan_and_apply_are_404_not_found(env):
    unknown = "12345678-1234-1234-1234-123456789abc"
    for path in (f"/api/scans/{unknown}", f"/api/applies/{unknown}"):
        r = env.client.get(path)
        assert r.status_code == 404 and r.json()["detail"] == "not found"


# ---------------------------------------------------------------------------
# Apply: secrets, dry run gating, stale scans, guardrails, exports
# ---------------------------------------------------------------------------


def test_secret_map_outside_allowed_schemas_is_rejected(env):
    body = {**DRY_BODY, "uc_secret_map": {"scope/key": "secrets/cat.other.name"}}
    r = env.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 400 and "allowed" in r.json()["detail"]


def test_secret_map_inside_allowed_schema_is_passed_on(env):
    body = {**DRY_BODY, "uc_secret_map": {"scope/key": "secrets/cat.sec.name"}}
    r = env.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 200
    assert json.loads(env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["uc_secret_map"]) == \
        {"scope/key": "secrets/cat.sec.name"}


def test_secret_schema_names_are_case_insensitive(env):
    body = {**DRY_BODY, "uc_secret_map": {"scope/key": "secrets/CAT.SEC.name"}}
    assert env.client.post("/api/applies", json=body, headers=OP).status_code == 200


def test_allow_secret_read_needs_install_flag(env, monkeypatch):
    body = {**DRY_BODY, "allow_secret_read": True}
    assert env.client.post("/api/applies", json=body, headers=OP).status_code == 400
    monkeypatch.setattr(main, "ALLOW_SECRET_READ", True)
    assert env.client.post("/api/applies", json=body, headers=OP).status_code == 200


def test_config_exposes_allowed_schemas_limits_and_scope(env):
    cfg = env.client.get("/api/config").json()
    assert cfg["secret_schemas"] == ["cat.sec"] and cfg["allow_secret_read"] is False
    assert cfg["max_scan_age_days"] == 14
    assert cfg["workspace_url"] == HOST and cfg["scan_scope"] == f"This app scans only {HOST}."


def test_scans_record_the_workspace_they_scanned(env):
    rows = env.client.get("/api/scans").json()
    assert rows[0]["workspace_url"] == HOST
    assert env.client.get(f"/api/scans/{SCAN}", headers=OP).json()["meta"]["workspace_url"] == HOST


def test_readiness_items_pass_label_and_action_through(env):
    readiness = {"status": "BLOCKED", "blockers": [{"type": "legacy_traffic", "item": "ep-a", "detail": "x",
                                                    "label": "Move callers", "action": "Point clients at ai_gateway"}],
                 "warnings": [{"type": "x", "item": "y", "detail": "z", "label": "Review", "action": "Check"}]}
    env.store["items"] = [{"item_type": "readiness", "payload": json.dumps(readiness)}]
    r = env.client.get(f"/api/scans/{SCAN}", headers=OP).json()["readiness"]
    assert r["blockers"][0]["label"] == "Move callers" and r["blockers"][0]["action"] == "Point clients at ai_gateway"
    assert r["warnings"][0]["label"] == "Review"


def test_execute_needs_a_dry_run_id(env):
    body = {k: v for k, v in EXECUTE_BODY.items() if k != "dry_run_id"}
    r = env.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 400 and "dry run" in r.json()["detail"]


def test_execute_follows_a_matching_dry_run(env):
    env.sdk.jobs.get_run.return_value = SimpleNamespace(job_parameters=job_params())
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=OP)
    assert r.status_code == 200
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert params["mode"] == "execute" and params["dry_run_id"] == EXECUTE_BODY["dry_run_id"]  # the job checks it too


def test_legacy_dry_run_without_stored_fingerprint_uses_the_job_parameters(env):
    # Dry runs from before the fingerprint column: the job run's parameters decide (a missing value uses its default).
    params = [SimpleNamespace(name=p.name, value=None, default="false") if p.name == "grants" else p
              for p in job_params()]
    env.sdk.jobs.get_run.return_value = SimpleNamespace(job_parameters=params)
    assert env.client.post("/api/applies", json=EXECUTE_BODY, headers=OP).status_code == 200
    env.sdk.jobs.get_run.return_value = SimpleNamespace(job_parameters=job_params(grants="false"))
    r = env.client.post("/api/applies", json={**EXECUTE_BODY, "grants": True}, headers=OP)
    assert r.status_code == 409 and "changed" in r.json()["detail"]


def test_execute_rejects_changed_options(env):
    env.sdk.jobs.get_run.return_value = SimpleNamespace(job_parameters=job_params())
    body = {**EXECUTE_BODY, "grants": True}
    r = env.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_a_dry_run_for_one_target_does_not_unlock_another(env):
    # The target is chosen in Apply now, so it is part of what the dry run checked.
    env.sdk.jobs.get_run.return_value = SimpleNamespace(job_parameters=job_params())
    r = env.client.post("/api/applies", json={**EXECUTE_BODY, "target_schema": "other_schema"}, headers=OP)
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_execute_rejects_a_dry_run_that_did_not_succeed(env):
    env.store["applies"][0]["status"] = "FAILED"
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=OP)
    assert r.status_code == 409


def test_execute_rejects_a_dry_run_of_another_scan(env):
    env.store["applies"][0]["scan_run_id"] = "other-scan"
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=OP)
    assert r.status_code == 409


def test_stored_fingerprint_gates_the_execute_without_reading_the_job(env):
    env.store["applies"][0]["fingerprint"] = stored_fingerprint()
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=OP)
    assert r.status_code == 200 and env.sdk.jobs.get_run.call_count == 0


def test_stored_fingerprint_rejects_changed_options(env):
    env.store["applies"][0]["fingerprint"] = stored_fingerprint()
    r = env.client.post("/api/applies", json={**EXECUTE_BODY, "grants": True}, headers=OP)
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_endpoint_order_does_not_change_the_fingerprint(env):
    env.store["applies"][0]["fingerprint"] = store.selection_fingerprint(
        {**job_params_dict(), "endpoints": "ep-b,ep-a"})
    r = env.client.post("/api/applies", json={**EXECUTE_BODY, "endpoints": ["ep-a", "ep-b"]}, headers=OP)
    assert r.status_code == 200


def job_params_dict(**over):
    return {"scan_run_id": SCAN, "endpoints": "ep-a", "target_catalog": "ai_gateway", "target_schema": "migrated",
            "uc_secret_map": "", "allow_secret_read": "false", "grants": "false", "ack_guardrails": "false", **over}


def test_smoke_test_is_a_job_parameter_and_force_never_is(env):
    env.store["applies"][0]["fingerprint"] = stored_fingerprint()
    env.client.post("/api/applies", json=EXECUTE_BODY, headers=OP)
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert params["smoke_test"] == "true" and "force" not in params
    env.client.post("/api/applies", json={**EXECUTE_BODY, "smoke_test": False}, headers=OP)
    assert env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["smoke_test"] == "false"
    env.client.post("/api/applies", json=DRY_BODY, headers=OP)
    dry = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert dry["smoke_test"] == "false" and "force" not in dry


def test_guardrails_end_to_end_from_real_plan_to_execute(env, tmp_path, monkeypatch):
    """Scan (real planner output), dry run with the acknowledgement, the job's own dry run outcome, then execute."""
    from test_planner import EXTERNAL, _ep
    import ug_migration_apply as job_apply
    from test_apply import FakeW, UC_MAP
    env.store["items"] = planner_scan_items(tmp_path)
    body = {**DRY_BODY, "endpoints": ["proj-a-gpt"]}
    execute = {**EXECUTE_BODY, "endpoints": ["proj-a-gpt"]}
    # Without the acknowledgement the dry run is still allowed (it shows what is blocked); execute is refused.
    assert env.client.post("/api/applies", json=body, headers=OP).status_code == 200
    r = env.client.post("/api/applies", json=execute, headers=OP)
    assert r.status_code == 400 and "guardrails" in r.json()["detail"]
    # The dry run with the acknowledgement: the job runs the planner on the same plan and stores the outcome.
    r = env.client.post("/api/applies", json={**body, "ack_guardrails": True}, headers=OP)
    assert r.status_code == 200
    dry_params = dict(env.sdk.jobs.run_now.call_args.kwargs["job_parameters"])
    assert dry_params["ack_guardrails"] == "true" and dry_params["mode"] == "dry_run"
    eps = [_ep(EXTERNAL)]
    monkeypatch.setattr(planner, "inventory", lambda _w: eps)
    results = job_apply.apply(FakeW(), ["proj-a-gpt"], "ai_gateway", "migrated", False,
                              job_apply.Secrets(FakeW(), UC_MAP, False, dry_run=True, allowed_schemas=["c.s"]),
                              str(tmp_path / "dry.jsonl"), ack_guardrails=True, apply_id=DRY)
    outcome, summary = job_apply.run_outcome(results)
    assert outcome == "SUCCEEDED"  # acknowledged guardrails don't make the dry run need attention
    assert [x["guardrails_not_migrated"] for x in results if x.get("type") == "model_service"][0]
    # The job stores the dry run row with the fingerprint of the parameters it received.
    env.store["applies"].append({"apply_id": DRY_OK, "mode": "dry_run", "started_at": now_ts(), "status": outcome, "job_run_id": "777",
                                 "scan_run_id": SCAN, "fingerprint": store.selection_fingerprint(dry_params)})
    r = env.client.post("/api/applies", json={**execute, "dry_run_id": DRY_OK, "ack_guardrails": True}, headers=OP)
    assert r.status_code == 200
    exec_params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert exec_params["mode"] == "execute" and exec_params["ack_guardrails"] == "true"
    assert exec_params["smoke_test"] == "true"


def test_app_uses_the_job_side_rules_not_copies():
    """The app imports the store, apply and planner modules, so the app and the jobs can't disagree on these rules."""
    import ug_migration_apply as apply_mod
    assert main.store is store and main.planner is planner and main.apply_rules is apply_mod
    assert main.FINGERPRINT_KEYS is store.FINGERPRINT_KEYS and main.PROBLEM_ACTIONS is apply_mod.PROBLEM_ACTIONS
    assert main.OPERATIONS is apply_mod.OPERATIONS and main.SERVICE_NAME_RE is apply_mod.SERVICE_NAME_RE
    assert main.CUTOVER_OPERATIONS == ("test_call", "pause_legacy", "enable_tracking", "resume_legacy", "guardrail_check")
    assert main.DRY_RUN_TTL_HOURS == apply_mod.DRY_RUN_TTL_HOURS
    for name in ("selection_fingerprint", "legacy_fingerprint", "rollback_done", "rollback_blocks", "effective_status",
                 "legacy_traffic_since", "ug_usage_summary", "ug_request_lookup", "_canon", "_since"):
        assert not hasattr(main, name) and not hasattr(main, "_" + name.lstrip("_")), name


def test_scan_export_marks_truncation(env, monkeypatch):
    item = {"payload": json.dumps({"legacy_endpoint": "ep-a"})}
    env.store["items"] = [item, item]
    monkeypatch.setattr(main, "EXPORT_ROW_LIMIT", 2)
    r = env.client.get(f"/api/scans/{SCAN}/export/plan", headers=as_user(OP_TOKEN, OP_EMAIL))
    assert r.status_code == 200 and r.headers.get("x-truncated") == "true"
    monkeypatch.setattr(main, "EXPORT_ROW_LIMIT", 5)
    r = env.client.get(f"/api/scans/{SCAN}/export/plan", headers=as_user(OP_TOKEN, OP_EMAIL))
    assert "x-truncated" not in r.headers


# ---------------------------------------------------------------------------
# Rollbacks: one definition of "rolled back", shown in the list and enforced on the rollback
# ---------------------------------------------------------------------------


def _execute_row(apply_id=EXEC, status="SUCCEEDED"):
    return {"apply_id": apply_id, "mode": "execute", "status": status, "job_run_id": "800", "scan_run_id": SCAN,
            "target_catalog": "ai_gateway", "target_schema": "migrated"}


RB_DRY = "dddddddd-1111-2222-3333-444444444444"


KEPT_SUMMARY = json.dumps({"would_delete": 1, "kept": 1, "kept_other_run": 1})  # what a dry run that keeps objects stores


def _rollback_dry_row(rollback_of=EXEC, status="SUCCEEDED", **over):
    summary = KEPT_SUMMARY if status == "NEEDS_ATTENTION" else json.dumps({"would_delete": 1})
    return {"apply_id": RB_DRY, "mode": "rollback_dry_run", "operation": "apply", "status": status, "job_run_id": "802",
            "rollback_of": rollback_of, "requested_by": OP_EMAIL, "started_at": now_ts(), "summary": summary, **over}


ROLLBACK_BODY = {"mode": "rollback", "rollback_of": EXEC, "confirm": "ROLLBACK", "dry_run_id": RB_DRY}


def test_a_rollback_dry_run_never_counts_as_rolled_back(env):
    env.store["applies"].append(_execute_row())
    env.store["rollbacks"] = [{**_rollback_dry_row(), "summary": "{}"}]
    rows = {r["apply_id"]: r for r in env.client.get("/api/applies", headers=OP).json()}
    assert rows[EXEC]["rolled_back"] is False
    assert env.client.get(f"/api/applies/{EXEC}", headers=OP).json()["meta"]["rolled_back"] is False
    env.store["applies"].append(_rollback_dry_row())
    assert env.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP).status_code == 200


def test_a_rollback_dry_run_says_why_it_cant_unlock_a_rollback(env):
    """The page shows the reason instead of the delete button; the server gate refuses the same runs."""
    env.store["applies"] += [_execute_row(), _rollback_dry_row()]
    meta = lambda: env.client.get(f"/api/applies/{RB_DRY}", headers=OP).json()["meta"]
    assert meta()["unlock_problem"] is None  # SUCCEEDED
    for status, summary, want, allowed in (
            ("NEEDS_ATTENTION", {"would_delete": 1, "kept": 2, "kept_other_run": 2}, None, True),  # kept: normal
            ("NEEDS_ATTENTION", {"would_delete": 1, "error": 1}, "other than kept", False),
            ("NEEDS_ATTENTION", None, "summary can't be read", False),
            ("FAILED", {}, None, False)):  # the page already says "Run failed"; the gate still refuses it
        env.store["applies"] = [r for r in env.store["applies"] if r["apply_id"] != RB_DRY] + [
            _rollback_dry_row(status=status, summary=None if summary is None else json.dumps(summary))]
        got = meta()["unlock_problem"]
        assert (got is None) if want is None else (want in (got or "")), (status, summary, got)
        gate = env.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP)
        assert (gate.status_code == 200) == allowed, (status, gate.text)
        env.sdk.jobs.run_now.reset_mock()


def test_a_used_rollback_dry_run_says_which_rollback_used_it(env):
    env.store["applies"] += [_execute_row(), _rollback_dry_row()]
    assert env.client.get(f"/api/applies/{RB_DRY}", headers=OP).json()["meta"]["used_by"] is None
    env.store["applies"].append({"apply_id": ROLLBACK, "mode": "rollback", "dry_run_id": RB_DRY, "status": "SUCCEEDED"})
    assert env.client.get(f"/api/applies/{RB_DRY}", headers=OP).json()["meta"]["used_by"] == ROLLBACK
    r = env.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP)
    assert r.status_code == 409 and "rollback dry run was already used by a rollback" in r.json()["detail"]


def test_rollback_needs_its_own_dry_run(env):
    env.store["applies"].append(_execute_row())
    # No dry run: refused before any job starts.
    r = env.client.post("/api/applies", json={"mode": "rollback", "rollback_of": EXEC, "confirm": "ROLLBACK"}, headers=OP)
    assert r.status_code == 400 and "rollback dry run" in r.json()["detail"] and env.sdk.jobs.run_now.call_count == 0
    # The dry run needs no typed word and starts a job with mode rollback_dry_run.
    r = env.client.post("/api/applies", json={"mode": "rollback_dry_run", "rollback_of": EXEC}, headers=OP)
    assert r.status_code == 200 and env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["mode"] == "rollback_dry_run"
    env.sdk.jobs.run_now.reset_mock()
    for bad, why in ((_rollback_dry_row(status="FAILED"), "didn't finish"),
                     (_rollback_dry_row(status="RUNNING"), "didn't finish"),
                     # NEEDS_ATTENTION with anything besides kept objects (an object it couldn't read) is refused,
                     # and so is one whose summary is missing or unreadable.
                     (_rollback_dry_row(status="NEEDS_ATTENTION", summary=json.dumps({"would_delete": 1, "error": 1})), "other than kept"),
                     (_rollback_dry_row(status="NEEDS_ATTENTION", summary=json.dumps({"kept": 1, "manual": 2})), "manual 2"),
                     (_rollback_dry_row(status="NEEDS_ATTENTION", summary=None), "summary can't be read"),
                     (_rollback_dry_row(status="NEEDS_ATTENTION", summary="not json"), "summary can't be read"),
                     (_rollback_dry_row(rollback_of=DRY_OK), "another execute run"),
                     (_rollback_dry_row(requested_by="someone@else.com"), "someone else"),
                     (_rollback_dry_row(started_at=now_ts(days_ago=2)), "hours old"),
                     (_rollback_dry_row(mode="dry_run"), "isn't a rollback dry run")):
        env.store["applies"] = [r for r in env.store["applies"] if r["apply_id"] != RB_DRY] + [bad]
        r = env.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP)
        assert r.status_code == 409 and why in r.json()["detail"], (why, r.text)
    assert env.sdk.jobs.run_now.call_count == 0
    # A dry run that keeps some objects finishes as NEEDS_ATTENTION ("kept" is a problem action): it still unlocks.
    for status in ("NEEDS_ATTENTION", "SUCCEEDED"):
        env.store["applies"] = [r for r in env.store["applies"] if r["apply_id"] != RB_DRY] + [_rollback_dry_row(status=status)]
        r = env.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP)
        params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
        assert r.status_code == 200 and params["mode"] == "rollback" and params["dry_run_id"] == RB_DRY, (status, r.text)
    # Each rollback dry run is good for one rollback.
    env.store["applies"].append({"apply_id": ROLLBACK, "mode": "rollback", "dry_run_id": RB_DRY, "status": "FAILED"})
    r = env.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP)
    assert r.status_code == 409 and "already used" in r.json()["detail"]


def test_applies_list_says_which_runs_are_rolled_back(env):
    env.store["applies"].append(_execute_row())
    env.store["rollbacks"] = [{"apply_id": ROLLBACK, "rollback_of": EXEC, "status": "NEEDS_ATTENTION",
                               "job_run_id": "801", "summary": json.dumps({"kept": 1, "kept_other_run": 1})}]
    rows = {r["apply_id"]: r for r in env.client.get("/api/applies", headers=OP).json()}
    assert rows[EXEC]["rolled_back"] is True and rows[DRY]["rolled_back"] is False
    assert env.client.get(f"/api/applies/{EXEC}", headers=OP).json()["meta"]["rolled_back"] is True


def test_rollback_is_refused_when_already_done(env):
    env.store["applies"].append(_execute_row())
    env.store["rollbacks"] = [{"apply_id": ROLLBACK, "rollback_of": EXEC, "status": "SUCCEEDED", "job_run_id": "801",
                               "summary": "{}"}]
    r = env.client.post("/api/applies", json={"mode": "rollback", "rollback_of": EXEC, "confirm": "ROLLBACK"}, headers=OP)
    assert r.status_code == 409 and "already been rolled back" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_rollback_is_allowed_again_after_a_failed_rollback(env):
    env.store["applies"].append(_execute_row())
    env.store["rollbacks"] = [{"apply_id": ROLLBACK, "rollback_of": EXEC, "status": "NEEDS_ATTENTION", "job_run_id": "801",
                               "summary": json.dumps({"error": 1, "kept_other_run": 0})}]
    env.store["applies"].append(_rollback_dry_row())
    r = env.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP)
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert r.status_code == 200 and params["rollback_of"] == EXEC and params["mode"] == "rollback"
    assert "force" not in params  # rolling back changed objects is a command-line decision


def test_rollback_is_refused_while_a_rollback_is_running(env):
    env.store["applies"].append(_execute_row())
    env.store["rollbacks"] = [{"apply_id": ROLLBACK, "rollback_of": EXEC, "status": "RUNNING", "job_run_id": "801",
                               "summary": None}]
    env.sdk.jobs.get_run.return_value = _job_state("RUNNING")
    r = env.client.post("/api/applies", json={"mode": "rollback", "rollback_of": EXEC, "confirm": "ROLLBACK"}, headers=OP)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Target schema (the user's own access) and config
# ---------------------------------------------------------------------------


def test_target_schema_missing(env, monkeypatch):
    monkeypatch.setattr(main, "query", lambda request, sql, params=None, **kw: [])
    r = env.client.get("/api/target-schema?catalog=ai_gateway&schema=migrated", headers=OP)
    assert r.json() == {"exists": False, "can_create_service": None, "error": None}


def test_target_schema_found_with_sql_not_rest(env, monkeypatch):
    seen = {}

    def fake_query(request, sql, params=None, **kw):
        seen["sql"], seen["params"] = sql, params
        return [{"found": 1}]
    monkeypatch.setattr(main, "query", fake_query)
    r = env.client.get("/api/target-schema?catalog=ai_gateway&schema=migrated", headers=OP)
    assert r.json() == {"exists": True, "can_create_service": None, "error": None}
    assert "`ai_gateway`.information_schema.schemata" in seen["sql"] and seen["params"] == {"s": "migrated"}


def test_target_schema_says_when_it_cannot_be_read(env, monkeypatch):
    def boom(request, sql, params=None, **kw):
        raise RuntimeError("catalog not found")
    monkeypatch.setattr(main, "query", boom)
    r = env.client.get("/api/target-schema?catalog=ai_gateway&schema=migrated", headers=OP).json()
    assert r["exists"] is False and "Couldn't read ai_gateway.migrated" in r["error"]


def test_target_schema_validates_names(env):
    r = env.client.get("/api/target-schema?catalog=ai%20gateway&schema=migrated", headers=OP)
    assert r.status_code == 400 and "letters" in r.json()["detail"]


# ---------------------------------------------------------------------------
# One deadline, and the mirrored verify builders, fingerprint and options agree with the job
# ---------------------------------------------------------------------------

PAUSE = "dddddddd-1111-2222-3333-444444444444"
TEST_RUN = "eeeeeeee-1111-2222-3333-444444444444"


def test_app_and_account_agree_on_the_deadline_and_old_wave_names():
    import ug_migration_account as acct
    assert main.LEGACY_DEADLINE == acct.LEGACY_DEADLINE == planner.LEGACY_DEADLINE == "2027-03-30"
    assert main.LEGACY_WAVE_NAMES == acct.LEGACY_WAVE_NAMES
    with pytest.raises(ValueError):
        main._validate_deadline("30/03/2027")


def test_config_carries_the_one_deadline(env):
    body = env.client.get("/api/config").json()
    assert body["deadline"] == "2027-03-30" and body["deadline_as_of"] == "2026-11-01"


def test_apply_and_cutover_lists_use_their_own_rows(env, monkeypatch):
    seen = []

    def spy(request, sql, params=None, **kw):
        seen.append(sql)
        return []
    monkeypatch.setattr(main, "query", spy)
    env.client.get("/api/applies", headers=OP)
    env.client.get("/api/cutover/runs", headers=OP)
    assert any("(operation IS NULL OR operation = 'apply')" in s for s in seen)
    assert any("operation IS NOT NULL AND operation <> 'apply'" in s for s in seen)


def _post(env, **body):
    return env.client.post("/api/cutover", json=body, headers=OP)


def _pause_scan(env, monkeypatch, requests=0, missing=False, failing=False):
    """A finished scan with ep-a and ep-b in its plan, and legacy traffic for ep-a (the pause gate reads it)."""
    env.store["scans"][0].update(workspace_id="984", days=30, finished_at=now_ts(1))
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "ep-a", "kind": "external_model"})},
        {"item_type": "plan", "seq": 2, "payload": json.dumps({"legacy_endpoint": "ep-b", "kind": "external_model"})},
    ]
    base = make_query(env.store)

    def fake(request, sql, params=None, missing_ok=True):
        if "system.serving.endpoint_usage" in sql:
            if missing and not missing_ok:
                raise main.TableMissing("Couldn't read a system table this check needs")
            if missing:
                return []
            if failing:
                raise main.HTTPException(502, "Query failed: warehouse stopped")
            return [{"source": "v1", "endpoint_name": "ep-a", "requester": "a@x.com", "requests": str(requests),
                     "last_request": "2026-11-01 10:00:00"}] if requests else []
        return base(request, sql, params)
    monkeypatch.setattr(main, "query", fake)


def test_cutover_is_operator_only(env):
    viewer = as_user(VIEWER_TOKEN, VIEWER_EMAIL)
    r = env.client.post("/api/cutover", json={"operation": "pause_legacy", "endpoints": ["ep-a"]}, headers=viewer)
    assert r.status_code == 403 and env.sdk.jobs.run_now.call_count == 0


def test_pause_takes_one_endpoint_and_the_typed_word(env):
    assert _post(env, operation="pause_legacy", endpoints=["ep-a", "ep-b"]).status_code == 400
    assert _post(env, operation="pause_legacy", endpoints=["bad name"]).status_code == 400
    r = _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], dry_run_id=DRY_OK, confirm="PAUSE ep-b")
    assert r.status_code == 400 and "type PAUSE to confirm" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_pause_dry_run_starts_the_apply_job_with_the_operation(env, monkeypatch):
    _pause_scan(env, monkeypatch)
    r = _post(env, operation="pause_legacy", endpoints=["ep-a"])
    assert r.status_code == 200, r.text
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert params["operation"] == "pause_legacy" and params["mode"] == "dry_run" and params["endpoints"] == "ep-a"
    assert params["apply_id"] == r.json()["apply_id"] and params["requested_by"] == OP_EMAIL
    assert params["rollback_of"] == "" and params["force"] == "false"


def test_execute_needs_a_matching_successful_dry_run(env, monkeypatch):
    _pause_scan(env, monkeypatch)
    stored = store.legacy_fingerprint({"operation": "pause_legacy", "endpoints": "ep-a"})
    env.store["applies"].append({"apply_id": DRY_OK, "mode": "dry_run", "started_at": now_ts(), "operation": "pause_legacy",
                                 "status": "SUCCEEDED", "job_run_id": "700", "fingerprint": stored})
    assert _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], confirm="PAUSE ep-a").status_code == 400
    r = _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], confirm="PAUSE ep-a", dry_run_id=DRY_OK)
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert r.status_code == 200 and params["mode"] == "execute" and params["dry_run_id"] == DRY_OK
    r = _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-b"], confirm="PAUSE ep-b", dry_run_id=DRY_OK)
    assert r.status_code == 409 and "changed" in r.json()["detail"]


def test_pause_word_is_just_pause_and_the_old_form_still_works(env, monkeypatch):
    _pause_scan(env, monkeypatch)
    stored = store.legacy_fingerprint({"operation": "pause_legacy", "endpoints": "ep-a"})
    env.store["applies"].append({"apply_id": DRY_OK, "mode": "dry_run", "started_at": now_ts(), "operation": "pause_legacy",
                                 "status": "SUCCEEDED", "job_run_id": "700", "fingerprint": stored})
    for word in ("PAUSE", "PAUSE ep-a"):
        r = _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], confirm=word, dry_run_id=DRY_OK)
        assert r.status_code == 200, (word, r.json())
    assert _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], confirm="pause",
                 dry_run_id=DRY_OK).status_code == 400


def test_a_dry_run_unlocks_one_execute(env, monkeypatch):
    _pause_scan(env, monkeypatch)
    stored = store.legacy_fingerprint({"operation": "pause_legacy", "endpoints": "ep-a"})
    env.store["applies"].append({"apply_id": DRY_OK, "mode": "dry_run", "started_at": now_ts(), "operation": "pause_legacy",
                                 "status": "SUCCEEDED", "job_run_id": "700", "fingerprint": stored})
    env.store["applies"].append({"apply_id": PAUSE, "mode": "execute", "started_at": now_ts(), "operation": "pause_legacy",
                                 "status": "SUCCEEDED", "job_run_id": "701", "dry_run_id": DRY_OK})
    r = _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], confirm="PAUSE", dry_run_id=DRY_OK)
    assert r.status_code == 409 and r.json()["detail"] == main.DRY_RUN_USED
    assert env.sdk.jobs.run_now.call_count == 0


def test_unmatched_legacy_requests_count_as_traffic_for_a_pause(env, monkeypatch):
    _pause_scan(env, monkeypatch)
    base = main.query

    def fake(request, sql, params=None, missing_ok=True):
        if "system.serving.endpoint_usage" in sql:
            return [{"source": "v1", "endpoint_name": store.UNATTRIBUTED, "requester": "x@y.com", "requests": "7",
                     "last_request": "2026-11-01 10:00:00"}]
        return base(request, sql, params, missing_ok=missing_ok)
    monkeypatch.setattr(main, "query", fake)
    r = _post(env, operation="pause_legacy", endpoints=["ep-a"], traffic_window="24h")
    assert r.status_code == 409 and "couldn't be matched" in r.json()["detail"]
    assert _post(env, operation="pause_legacy", endpoints=["ep-a"], traffic_window="24h", ack_traffic=True).status_code == 200
    t = env.client.get(f"/api/cutover/traffic?window=24h&scan_run_id={SCAN}", headers=OP).json()
    assert t["total_requests"] == 7 and any(e["endpoint_name"] == store.UNATTRIBUTED for e in t["endpoints"])


def test_config_names_a_second_install(env, monkeypatch):
    monkeypatch.setattr(main, "APP_NAME", "ugmig-live")
    c = env.client.get("/api/config", headers=OP).json()
    assert c["app_name"] == "ugmig-live" and c["default_app_name"] == "ug-migration-toolkit"


def test_a_dry_run_of_another_operation_does_not_count(env):
    stored = store.legacy_fingerprint({"operation": "enable_tracking", "endpoints": "ep-a"})
    env.store["applies"].append({"apply_id": DRY_OK, "mode": "dry_run", "started_at": now_ts(), "operation": "enable_tracking",
                                 "status": "SUCCEEDED", "job_run_id": "700", "fingerprint": stored})
    r = _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], confirm="PAUSE ep-a", dry_run_id=DRY_OK)
    assert r.status_code == 400 and env.sdk.jobs.run_now.call_count == 0


def test_pause_with_traffic_needs_the_acknowledgement_on_the_server(env, monkeypatch):
    _pause_scan(env, monkeypatch, requests=7)
    r = _post(env, operation="pause_legacy", endpoints=["ep-a"], scan_run_id=SCAN)
    assert r.status_code == 409 and "7 legacy requests" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0
    assert _post(env, operation="pause_legacy", endpoints=["ep-a"], scan_run_id=SCAN, ack_traffic=True).status_code == 200
    # The acknowledgement is the job's force override (the job refuses recent traffic without it), and it is part of
    # the fingerprint, so the execute must carry it too.
    assert env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["force"] == "true"
    assert "dry_run_id" not in env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert _post(env, operation="pause_legacy", endpoints=["ep-a"], traffic_window="1y").status_code == 400


@pytest.mark.parametrize("missing, failing", [(True, False), (False, True)])
def test_pause_is_refused_when_traffic_cannot_be_read(env, monkeypatch, missing, failing):
    _pause_scan(env, monkeypatch, missing=missing, failing=failing)
    r = _post(env, operation="pause_legacy", endpoints=["ep-a"], ack_traffic=True)
    assert r.status_code == 409 and "wasn't paused" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_traffic_check_with_a_missing_system_table_is_unknown_not_zero(env, monkeypatch):
    _pause_scan(env, monkeypatch, missing=True)
    r = env.client.get("/api/cutover/traffic?window=24h", headers=OP).json()
    assert r["total_requests"] is None and r["endpoints"] == [] and "system table" in r["traffic_error"]


def test_pause_of_an_endpoint_outside_the_plan_is_refused(env, monkeypatch):
    _pause_scan(env, monkeypatch)
    r = _post(env, operation="pause_legacy", endpoints=["ep-z"])
    assert r.status_code == 409 and "plan" in r.json()["detail"]


def test_old_dry_runs_expire(env, monkeypatch):
    _pause_scan(env, monkeypatch)
    stored = store.legacy_fingerprint({"operation": "pause_legacy", "endpoints": "ep-a"})
    env.store["applies"].append({"apply_id": DRY_OK, "mode": "dry_run", "operation": "pause_legacy",
                                 "started_at": now_ts(days_ago=main.DRY_RUN_TTL_HOURS / 24 + 0.1),
                                 "status": "SUCCEEDED", "job_run_id": "700", "fingerprint": stored})
    r = _post(env, operation="pause_legacy", mode="execute", endpoints=["ep-a"], confirm="PAUSE ep-a", dry_run_id=DRY_OK)
    assert r.status_code == 409 and "hours old" in r.json()["detail"]
    env.store["applies"][0]["started_at"] = now_ts(days_ago=2)
    r = env.client.post("/api/applies", json=EXECUTE_BODY, headers=OP)
    assert r.status_code == 409 and "hours old" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_run_details_and_exports_are_for_the_requester_operators_and_admins(env, monkeypatch):
    viewer, other = as_user(VIEWER_TOKEN, VIEWER_EMAIL), "zz@example.com"
    env.store["applies"][0]["requested_by"] = OP_EMAIL
    env.store["scans"][0]["requested_by"] = other
    paths = [f"/api/scans/{SCAN}", f"/api/scans/{SCAN}/refs", f"/api/scans/{SCAN}/export/plan",
             f"/api/applies/{DRY}", f"/api/applies/{DRY}/export"]
    monkeypatch.setattr(main, "APPLY_RUNS", "1 = 1")
    for path in paths:
        assert env.client.get(path, headers=viewer).status_code == 403, path
        assert env.client.get(path, headers=OP).status_code == 200, path
    env.store["scans"][0]["requested_by"] = VIEWER_EMAIL
    assert env.client.get(f"/api/scans/{SCAN}", headers=viewer).status_code == 200
    # A workspace admin who isn't an operator can read every run.
    monkeypatch.setattr(main, "is_workspace_admin", lambda request: True)
    assert env.client.get(f"/api/applies/{DRY}/export", headers=viewer).status_code == 200
    assert env.client.get(f"/api/applies/{DRY}", headers=as_user("bogus")).status_code == 401


def test_cutover_run_detail_and_export_check_the_requester(env):
    run = "dddddddd-1111-2222-3333-444444444444"
    env.store["applies"].append({"apply_id": run, "mode": "execute", "operation": "test_call", "status": "SUCCEEDED",
                                 "requested_by": OP_EMAIL, "job_run_id": "1"})
    viewer = as_user(VIEWER_TOKEN, VIEWER_EMAIL)
    for path in (f"/api/cutover/{run}", f"/api/cutover/{run}/export"):
        assert env.client.get(path, headers=viewer).status_code == 403, path
        assert env.client.get(path, headers=OP).status_code == 200, path


def test_workspace_admin_comes_from_the_token_groups(env, monkeypatch):
    class AdminWC(FakeWC):
        def me(self):
            return SimpleNamespace(user_name=TOKENS[self._token], groups=[SimpleNamespace(display="admins")])
    monkeypatch.setattr(main, "WorkspaceClient", AdminWC)
    assert main.is_workspace_admin(SimpleNamespace(headers={"x-forwarded-access-token": VIEWER_TOKEN})) is True
    monkeypatch.setattr(main, "_admins", {})
    monkeypatch.setattr(main, "WorkspaceClient", FakeWC)
    assert main.is_workspace_admin(SimpleNamespace(headers={"x-forwarded-access-token": VIEWER_TOKEN})) is False
    assert main.is_workspace_admin(SimpleNamespace(headers={})) is False


def test_test_call_says_who_it_runs_as(env):
    env.sdk.jobs.get.return_value = SimpleNamespace(settings=SimpleNamespace(
        run_as=SimpleNamespace(service_principal_name="sp-app-123", user_name=None)), creator_user_name="admin@x.com")
    r = _post(env, operation="test_call", services=["system.ai.gpt-5-mini"])
    assert r.status_code == 200 and r.json()["runs_as"] == "sp-app-123"
    assert env.client.get("/api/config").json()["jobs_run_as"] == "sp-app-123"


def test_test_call_checks_services_api_type_and_prompt(env):
    ok = {"operation": "test_call", "services": ["system.ai.gpt-5-mini"]}
    assert _post(env, **{**ok, "services": []}).status_code == 400
    assert _post(env, **{**ok, "services": ["gpt-5-mini"]}).status_code == 400
    assert _post(env, **{**ok, "api_type": "anthropic/v1"}).status_code == 400
    assert _post(env, **{**ok, "prompt": "line\none"}).status_code == 400
    assert _post(env, **{**ok, "prompt": "x" * 201}).status_code == 400
    assert env.sdk.jobs.run_now.call_count == 0
    r = _post(env, **ok)
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert r.status_code == 200 and params["operation"] == "test_call"
    assert params["services"] == "system.ai.gpt-5-mini" and params["prompt"] == "Reply with: ok"
    assert params["api_type"] == "mlflow/v1/chat/completions"


def test_resume_needs_an_executed_pause_run_and_the_word(env, monkeypatch):
    env.store["applies"].append({"apply_id": PAUSE, "mode": "execute", "operation": "pause_legacy",
                                 "status": "SUCCEEDED", "job_run_id": "710", "summary": "{}"})
    assert _post(env, operation="resume_legacy", mode="execute", rollback_of=PAUSE).status_code == 400
    assert _post(env, operation="resume_legacy", mode="execute", rollback_of=DRY, confirm="RESUME").status_code == 400
    r = _post(env, operation="resume_legacy", mode="execute", rollback_of=PAUSE, confirm="RESUME")
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert r.status_code == 200 and params["operation"] == "resume_legacy" and params["mode"] == "execute"
    assert params["rollback_of"] == PAUSE
    env.store["rollbacks"] = [{"apply_id": ROLLBACK, "rollback_of": PAUSE, "status": "SUCCEEDED", "job_run_id": "711",
                               "summary": "{}"}]
    assert _post(env, operation="resume_legacy", mode="execute", rollback_of=PAUSE, confirm="RESUME").status_code == 409


def test_apply_rollback_refuses_a_pause_run(env):
    env.store["applies"].append({"apply_id": PAUSE, "mode": "execute", "operation": "pause_legacy",
                                 "status": "SUCCEEDED", "job_run_id": "710", "summary": "{}"})
    r = env.client.post("/api/applies", json={"mode": "rollback", "rollback_of": PAUSE, "confirm": "ROLLBACK"}, headers=OP)
    assert r.status_code == 400 and "Verify & cut over" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


def test_cutover_conflict_names_the_running_job(env):
    env.store["items"] = [{"item_type": "plan", "seq": 1,
                           "payload": json.dumps({"legacy_endpoint": "ep-a", "kind": "external_model"})}]
    env.sdk.jobs.list_runs.side_effect = lambda **kw: iter([SimpleNamespace(run_id=42, run_page_url="https://ws/job/42")])
    r = _post(env, operation="enable_tracking", endpoints=["ep-a"], scan_run_id=env.store["scans"][0]["run_id"])
    assert r.status_code == 409 and r.json()["job_run_id"] == "42" and r.json()["url"] == "https://ws/job/42"
    assert env.sdk.jobs.run_now.call_count == 0


def test_traffic_lists_every_legacy_endpoint_with_its_class_from_the_scan(env, monkeypatch):
    env.store["scans"][0].update(workspace_id="984", days=30, finished_at=now_ts(1))
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "ep-a", "kind": "external_model"})},
        {"item_type": "plan", "seq": 2, "payload": json.dumps({"legacy_endpoint": "ep-b", "kind": "v2_workspace_endpoint"})},
        {"item_type": "plan", "seq": 3, "payload": json.dumps({"legacy_endpoint": "ep-c", "kind": "custom_model"})},
        {"item_type": "plan", "seq": 4, "payload": json.dumps({"legacy_endpoint": "ep-d", "kind": "external_model"})},
        {"item_type": "caller", "seq": 5, "payload": json.dumps({"endpoint_name": "ep-a", "requester": "a@x.com",
                                                                 "caller_class": "user"})},
    ]
    seen = {}
    base = make_query(env.store)

    def fake(request, sql, params=None, **kw):
        if "system.serving.endpoint_usage" in sql:
            seen["params"] = params
            return [{"source": "v1", "endpoint_name": "ep-a", "requester": "a@x.com", "requests": "3",
                     "last_request": "2026-11-01 10:00:00"},
                    {"source": "v2", "endpoint_name": "ep-b", "requester": "svc", "requests": "2",
                     "last_request": "2026-11-01 09:00:00"}]
        return base(request, sql, params)
    monkeypatch.setattr(main, "query", fake)
    r = env.client.get("/api/cutover/traffic?window=7d", headers=OP).json()
    by = {e["endpoint_name"]: e for e in r["endpoints"]}
    assert set(by) == {"ep-a", "ep-b", "ep-d"}  # the custom model endpoint is not a legacy endpoint
    assert by["ep-a"]["requests"] == 3 and by["ep-a"]["status"] == "requests"
    assert by["ep-a"]["callers"][0]["caller_class"] == "user"
    assert by["ep-b"]["kind"] == "v2_workspace_endpoint" and by["ep-b"]["callers"][0]["caller_class"] is None
    assert by["ep-d"]["status"] == "no_requests" and by["ep-d"]["requests"] == 0
    assert r["total_requests"] == 5 and r["workspace_id"] == "984" and r["since"]
    assert seen["params"]["workspace_id"] == "984" and seen["params"]["v2_1"] == "ep-b"


def test_traffic_counts_failed_and_tokens_and_flags_v2_calls_that_fail(env, monkeypatch):
    env.store["scans"][0].update(workspace_id="984", days=30, finished_at=now_ts(1))
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "ep-a", "kind": "external_model"})},
        {"item_type": "plan", "seq": 2, "payload": json.dumps({"legacy_endpoint": "ep-b", "kind": "v2_workspace_endpoint"})},
    ]
    base = make_query(env.store)

    def fake(request, sql, params=None, **kw):
        if "system.serving.endpoint_usage" in sql:
            return [{"source": "v1", "endpoint_name": "ep-a", "requester": "a@x.com", "requests": "10", "failed": "1",
                     "tokens": "2500", "last_request": "2026-11-01 10:00:00"},
                    {"source": "v2", "endpoint_name": "ep-b", "requester": "svc", "requests": "40", "failed": "40",
                     "tokens": "0", "last_request": "2026-11-01 09:00:00"},
                    {"source": "v2", "endpoint_name": "ep-b", "requester": "dev@x.com", "requests": "2", "failed": "1",
                     "tokens": "900", "last_request": "2026-11-01 08:00:00"}]
        return base(request, sql, params)
    monkeypatch.setattr(main, "query", fake)
    r = env.client.get("/api/cutover/traffic?window=7d", headers=OP).json()
    by = {e["endpoint_name"]: e for e in r["endpoints"]}
    assert by["ep-a"]["tokens"] == 2500 and by["ep-a"]["failed"] == 1 and by["ep-a"]["v2_failing"] is False
    assert by["ep-b"]["requests"] == 42 and by["ep-b"]["failed"] == 41 and by["ep-b"]["tokens"] == 900
    assert by["ep-b"]["v2_requests"] == 42 and by["ep-b"]["v2_failed"] == 41 and by["ep-b"]["v2_failing"] is True
    assert by["ep-b"]["callers"][0]["failed"] == 40 and by["ep-b"]["callers"][0]["tokens"] == 0
    # The app's rule is the planner's rule: at least 10 v2 requests and 95% of them failed.
    assert main.V2_FAILING_MIN_REQUESTS == planner.V2_FAILING_MIN_REQUESTS
    assert main.V2_FAILING_SHARE_PERCENT == planner.V2_FAILING_SHARE_PERCENT
    assert main.v2_mostly_failing(9, 9) is False and main.v2_mostly_failing(10, 9) is False
    assert main.v2_mostly_failing(100, 95) is True and main.v2_mostly_failing(100, 94) is False


def test_traffic_window_and_scan_errors(env):
    assert env.client.get("/api/cutover/traffic?window=2d", headers=OP).status_code == 400
    env.store["scans"][0]["workspace_id"] = None
    assert env.client.get("/api/cutover/traffic?window=24h", headers=OP).status_code == 409


def test_usage_inputs_are_checked_and_the_export_is_guarded(env, monkeypatch):
    rows = [{"service_name": '=HYPERLINK("x")', "workspace_id": "1", "requester": "a@x.com",
             "api_type": "mlflow/v1/chat/completions", "destination_model": "gpt", "requests": "2",
             "invocations": "2", "total_tokens": "10", "average_latency_ms": "100", "p95_latency_ms": "200",
             "error_invocations": "0", "last_request": "2026-11-01 10:00:00"}]
    monkeypatch.setattr(main, "query", lambda request, sql, params=None, **kw: rows)
    assert env.client.get("/api/usage/summary?window=2d", headers=OP).status_code == 400
    assert env.client.get("/api/usage/summary?service=a.b", headers=OP).status_code == 400
    r = env.client.get("/api/usage/summary?window=7d&service=system.ai.gpt-5-mini", headers=OP)
    assert r.status_code == 200 and r.json()["rows"][0]["requests"] == "2"
    ex = env.client.get("/api/usage/summary/export?window=7d", headers=OP)
    assert ex.status_code == 200 and "'=HYPERLINK" in ex.text and ex.headers["content-type"].startswith("text/csv")
    assert env.client.get("/api/usage/request?request_id=has%20space", headers=OP).status_code == 400
    assert env.client.get("/api/usage/request?request_id=req-1", headers=OP).json()["rows"] == rows




def test_cutover_lists_pay_per_token_endpoints_for_pause_but_not_for_tracking(env):
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "databricks-gpt-x", "kind": "system_ppt",
                                                                "action": "use_system_ai"})},
        {"item_type": "plan", "seq": 2, "payload": json.dumps({"legacy_endpoint": "ext-a", "kind": "external_model",
                                                                "action": "create_model_service"})},
        {"item_type": "plan", "seq": 3, "payload": json.dumps({"legacy_endpoint": "v2-a", "kind": "v2_workspace_endpoint"})},
    ]
    assert "system_ppt" not in main.NOT_OPERABLE_KINDS and "system_ppt" in main.NOT_TRACKABLE_KINDS
    assert "v2_workspace_endpoint" in main.NOT_OPERABLE_KINDS


def test_cutover_lists_custom_endpoints_for_tracking_only(env):
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "my-agent", "kind": "custom_model",
                                                                "action": "out_of_scope"})},
        {"item_type": "plan", "seq": 2, "payload": json.dumps({"legacy_endpoint": "ka-1", "kind": "agent"})},
    ]
    r = env.client.get("/api/cutover/endpoints", headers=OP).json()
    by = {e["endpoint"]: e for e in r["endpoints"]}
    assert set(by) == {"my-agent"} and by["my-agent"]["trackable"] and not by["my-agent"]["pausable"]


def test_create_uc_secrets_is_passed_on_with_the_chosen_names(env):
    body = {**DRY_BODY, "create_uc_secrets": True, "uc_secret_map": {"scope/key": "secrets/cat.sec.scope_key"}}
    r = env.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 200
    params = env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert params["create_uc_secrets"] == "true"
    assert json.loads(params["uc_secret_map"]) == {"scope/key": "secrets/cat.sec.scope_key"}
    env.client.post("/api/applies", json=DRY_BODY, headers=OP)
    assert env.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["create_uc_secrets"] == "false"


def test_create_uc_secrets_needs_an_allowed_schema_and_excludes_copying(env, monkeypatch):
    body = {**DRY_BODY, "create_uc_secrets": True, "uc_secret_map": {"scope/key": "secrets/cat.sec.scope_key"}}
    monkeypatch.setattr(main, "ALLOW_SECRET_READ", True)
    r = env.client.post("/api/applies", json={**body, "allow_secret_read": True}, headers=OP)
    assert r.status_code == 400 and "one way" in r.json()["detail"]
    monkeypatch.setattr(main, "SECRET_SCHEMAS", set())
    r = env.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 400 and "allowed secret schema" in r.json()["detail"]


def test_a_dry_run_without_created_secrets_does_not_unlock_an_execute_that_creates_them(env):
    m = {"scope/key": "secrets/cat.sec.scope_key"}
    env.store["applies"][0]["fingerprint"] = store.selection_fingerprint(job_params_dict(uc_secret_map=json.dumps(m)))
    r = env.client.post("/api/applies", json={**EXECUTE_BODY, "uc_secret_map": m, "create_uc_secrets": True}, headers=OP)
    assert r.status_code == 409


def test_guardrail_check_needs_pairs_and_the_check_word():
    body = main.CutoverRequest(operation="guardrail_check", endpoints=["gov=c.s.gov"])
    p = main._cutover_params(body)
    assert p["endpoints"] == "gov=c.s.gov" and main._confirm_word("guardrail_check", p["endpoints"]) == "CHECK"
    with pytest.raises(main.HTTPException):
        main._cutover_params(main.CutoverRequest(operation="guardrail_check", endpoints=["gov"]))


def test_pt_endpoints_are_not_offered_or_accepted_for_pause(env):
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "pt-a", "kind": "provisioned_throughput",
                                                                "action": "create_model_service"})},
        {"item_type": "plan", "seq": 2, "payload": json.dumps({"legacy_endpoint": "ext-a", "kind": "external_model",
                                                                "action": "create_model_service"})},
    ]
    eps = {e["endpoint"]: e for e in env.client.get("/api/cutover/endpoints").json()["endpoints"]}
    assert eps["pt-a"]["pausable"] is False and eps["ext-a"]["pausable"] is True
    r = env.client.post("/api/cutover", json={"operation": "pause_legacy", "mode": "dry_run", "scan_run_id": SCAN,
                                              "endpoints": ["pt-a"]}, headers=OP)
    assert r.status_code == 409 and "provisioned throughput" in r.json()["detail"]
    env.sdk.jobs.run_now.assert_not_called()


def test_test_call_refuses_a_service_the_toolkit_neither_planned_nor_created(env):
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "ext-a", "kind": "external_model",
                                                                "action": "create_model_service",
                                                                "target_service": "ai_gateway.migrated.ext-a"})},
    ]
    r = env.client.post("/api/cutover", json={"operation": "test_call", "mode": "dry_run", "scan_run_id": SCAN,
                                              "services": ["someone.else.expensive"]}, headers=OP)
    assert r.status_code == 400 and "only go to system.ai" in r.json()["detail"]
    env.sdk.jobs.run_now.assert_not_called()
    for ok in ("ai_gateway.migrated.ext-a", "system.ai.some-model"):
        r = env.client.post("/api/cutover", json={"operation": "test_call", "mode": "dry_run", "scan_run_id": SCAN,
                                                  "services": [ok]}, headers=OP)
        assert r.status_code == 200, r.text



def test_tracking_is_refused_for_endpoints_the_scan_doesnt_mark_trackable(env):
    """Security review (Nov 4): a named endpoint must be a trackable endpoint of the scan's plan, not just a valid name."""
    env.store["items"] = [
        {"item_type": "plan", "seq": 1, "payload": json.dumps({"legacy_endpoint": "my-agent", "kind": "custom_model"})},
        {"item_type": "plan", "seq": 2, "payload": json.dumps({"legacy_endpoint": "databricks-llm", "kind": "system_ppt"})},
    ]
    for names in (["databricks-llm"], ["not-in-the-plan"], ["my-agent", "not-in-the-plan"]):
        r = _post(env, operation="enable_tracking", endpoints=names, scan_run_id=env.store["scans"][0]["run_id"])
        assert r.status_code == 400 and "only turned on for endpoints the scan's plan lists" in r.json()["detail"], names
    r = _post(env, operation="enable_tracking", endpoints=["my-agent"])
    assert r.status_code == 400 and "Choose the scan" in r.json()["detail"]
    assert env.sdk.jobs.run_now.call_count == 0


# ---- Operators in Settings: a table in the results schema, edited by workspace admins, read and written as the app


def operators_table(monkeypatch, env, rows):
    """The operators table behind main.app_query, recording what the app ran."""
    calls = []

    def fake(sql, params=None, missing_ok=True):
        assert "ug_migration_operators" in sql, "the app's own identity reads and writes only the operators table"
        calls.append((sql, dict(params or {})))
        if sql.startswith("SELECT"):
            return [dict(r) for r in rows]
        if sql.startswith("INSERT"):
            rows.append({"email": params["email"], "added_by": params["by"]})
        elif sql.startswith("DELETE"):
            rows[:] = [r for r in rows if r["email"] != params["email"]]
        return []

    monkeypatch.setattr(main, "app_query", fake)
    return calls


def test_an_operator_in_the_table_can_start_jobs(env, monkeypatch):
    monkeypatch.setattr(main, "OPERATORS", set())
    rows = []
    operators_table(monkeypatch, env, rows)
    assert env.client.post("/api/account/snapshot", json={}, headers=as_user(VIEWER_TOKEN)).status_code == 403
    rows.append({"email": VIEWER_EMAIL})
    main._operators["until"] = 0.0
    assert env.client.post("/api/account/snapshot", json={}, headers=as_user(VIEWER_TOKEN)).status_code == 200
    assert env.client.get("/api/whoami", headers=as_user(VIEWER_TOKEN)).json()["operator"] is True


def test_an_unreadable_operators_table_fails_closed(env, monkeypatch):
    monkeypatch.setattr(main, "OPERATORS", set())

    def missing(sql, params=None, missing_ok=True):
        raise main.TableMissing("no table")

    monkeypatch.setattr(main, "app_query", missing)
    assert env.client.post("/api/account/snapshot", json={}, headers=as_user(OP_TOKEN)).status_code == 403
    r = env.client.get("/api/settings/operators", headers=as_user(OP_TOKEN)).json()
    assert r["operators"] == [] and "run the installer again" in r["error"]


def test_only_workspace_admins_change_operators_and_the_email_is_bound(env, monkeypatch):
    rows = [{"email": "a@example.com", "added_by": "x"}]
    calls = operators_table(monkeypatch, env, rows)
    r = env.client.post("/api/settings/operators", json={"email": "b@example.com", "add": True}, headers=OP)
    assert r.status_code == 403 and "workspace admins" in r.json()["detail"]  # an operator isn't enough
    listed = env.client.get("/api/settings/operators", headers=OP).json()
    assert listed["can_edit"] is False
    assert [o["email"] for o in listed["operators"]] == ["a@example.com", OP_EMAIL]
    assert listed["operators"][1]["source"] == "deployment"
    monkeypatch.setattr(main, "is_workspace_admin", lambda request: True)
    r = env.client.post("/api/settings/operators", json={"email": " B@Example.com ", "add": True}, headers=OP)
    assert r.status_code == 200 and r.json()["can_edit"] is True
    assert [o["email"] for o in r.json()["operators"]] == ["a@example.com", "b@example.com", OP_EMAIL]
    insert = [c for c in calls if c[0].startswith("INSERT")]
    assert insert == [(insert[0][0], {"email": "b@example.com", "by": OP_EMAIL})] and "b@example.com" not in insert[0][0]
    r = env.client.post("/api/settings/operators", json={"email": "a@example.com", "add": False}, headers=OP)
    assert [o["email"] for o in r.json()["operators"]] == ["b@example.com", OP_EMAIL]
    r = env.client.post("/api/settings/operators", json={"email": OP_EMAIL, "add": False}, headers=OP)
    assert r.status_code == 409 and "deployment" in r.json()["detail"]
    for bad in ("not-an-email", "a@b.com,c@d.com", "x'@y.com"):
        r = env.client.post("/api/settings/operators", json={"email": bad, "add": True}, headers=OP)
        assert r.status_code == 400, bad


def test_changing_operators_is_a_json_post_from_this_site(env, monkeypatch):
    operators_table(monkeypatch, env, [])
    monkeypatch.setattr(main, "is_workspace_admin", lambda request: True)
    r = env.client.post("/api/settings/operators", json={"email": "b@example.com", "add": True},
                        headers={**OP, "sec-fetch-site": "cross-site"})
    assert r.status_code == 403
