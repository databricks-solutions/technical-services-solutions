"""Central mode (phase 1): one install scans other allowlisted workspaces of the account, read-only.

Covers the planner helpers, the scan notebook's checks (allowlist, URL from the account table, service principal
credentials, secret never logged), the installer's widgets and job parameters, and the app (config, workspaces,
scan start, and changes refused for scans of other workspaces)."""

import json
import pathlib
from types import SimpleNamespace

import pytest

import ug_migration_planner as planner
import ug_migration_store as store

HUB, REMOTE, OTHER = "1111111111111111", "2222222222222222", "3333333333333333"
SP_ID = "12345678-1234-1234-1234-123456789012"
SECRET_VALUE = "dose-not-a-real-oauth-secret"
NB_PATH = pathlib.Path(__file__).parent / "notebook" / "run_scan.py"


# ---------- planner helpers ----------

def test_parse_workspace_ids_keeps_numbers_and_rejects_the_rest():
    assert planner.parse_workspace_ids(f" {REMOTE}, {OTHER},{REMOTE} ,") == [REMOTE, OTHER]
    assert planner.parse_workspace_ids("") == []
    with pytest.raises(ValueError, match="numbers"):
        planner.parse_workspace_ids("adb-123")


class FakeRemote:
    def __init__(self, **kw):
        self.kw = kw
        self.config = SimpleNamespace(host=kw["host"])


def test_remote_client_uses_the_service_principal_and_checks_the_workspace(monkeypatch):
    monkeypatch.setattr(planner, "workspace_id_of", lambda c: REMOTE)
    c = planner.remote_workspace_client(REMOTE, [REMOTE], "https://adb-2.azuredatabricks.net/", SP_ID, SECRET_VALUE,
                                        factory=FakeRemote)
    assert c.kw == {"host": "https://adb-2.azuredatabricks.net", "client_id": SP_ID, "client_secret": SECRET_VALUE,
                    "auth_type": "oauth-m2m"}


@pytest.mark.parametrize("target,allow,url,cid,secret,err", [
    (OTHER, [REMOTE], "https://adb-3.net", SP_ID, "s", PermissionError),          # not allowlisted
    (REMOTE, [REMOTE], "http://adb-2.net", SP_ID, "s", ValueError),                # not https
    (REMOTE, [REMOTE], "https://evil.net/x?y", SP_ID, "s", ValueError),           # not a bare host
    (REMOTE, [REMOTE], "", SP_ID, "s", ValueError),                                # no URL in the account table
    (REMOTE, [REMOTE], "https://adb-2.net", "", "s", ValueError),                  # no client id
])
def test_remote_client_refuses_before_any_call(monkeypatch, target, allow, url, cid, secret, err):
    made = []
    with pytest.raises(err):
        planner.remote_workspace_client(target, allow, url, cid, secret, factory=lambda **k: made.append(k))
    assert made == []


def test_remote_client_refuses_a_url_that_answers_as_another_workspace(monkeypatch):
    monkeypatch.setattr(planner, "workspace_id_of", lambda c: OTHER)
    with pytest.raises(ValueError, match="answers as workspace"):
        planner.remote_workspace_client(REMOTE, [REMOTE], "https://adb-2.net", SP_ID, "s", factory=FakeRemote)


def test_remote_scan_notes_unity_catalog_definitions_as_not_scanned(monkeypatch):
    notes = {}
    scanner = SimpleNamespace(note=lambda k, v: notes.__setitem__(k, v),
                              scan_text=lambda *a: (_ for _ in ()).throw(AssertionError("no UC rows from the hub")))
    monkeypatch.setattr(planner, "_sql", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no hub query")))
    monkeypatch.setattr(planner, "REMOTE_SCAN", True)
    planner.scan_uc_sql(None, scanner, None)
    assert set(notes) == {"uc_functions_skipped", "uc_views_skipped"}
    assert all(v.startswith(planner.NOT_SCANNED) for v in notes.values())


# ---------- the scan notebook ----------

class ScanSpark:
    def __init__(self, url):
        self.url, self.queries = url, []

    def sql(self, text, args=None):
        self.queries.append((text, args))
        rows = [{"workspace_url": self.url}] if "workspaces_latest" in text and self.url is not None else []
        return SimpleNamespace(collect=lambda: rows)


def _scan_notebook(monkeypatch, params, url="adb-2222222222222222.2.azuredatabricks.net"):
    import databricks.sdk as sdk
    calls = {"upserts": [], "runs": [], "clients": [], "secret_reads": [], "logs": []}
    widgets = dict(params)
    dbutils = SimpleNamespace(
        widgets=SimpleNamespace(text=lambda name, default: widgets.setdefault(name, default), get=lambda n: widgets[n]),
        secrets=SimpleNamespace(get=lambda scope, key: calls["secret_reads"].append((scope, key)) or SECRET_VALUE),
        notebook=SimpleNamespace(
            entry_point=SimpleNamespace(getDbutils=lambda: SimpleNamespace(notebook=lambda: SimpleNamespace(
                getContext=lambda: SimpleNamespace(notebookPath=lambda: SimpleNamespace(
                    get=lambda: "/Workspace/Users/tester/ug/notebook/run_scan"))))),
            exit=lambda text: calls.__setitem__("exit", text)))
    hub = SimpleNamespace(config=SimpleNamespace(host="https://adb-1111111111111111.1.azuredatabricks.net"))

    def factory(*a, **k):
        if not k:
            return hub
        calls["clients"].append(k)
        return SimpleNamespace(config=SimpleNamespace(host=k["host"]), kw=k)

    monkeypatch.setattr(sdk, "WorkspaceClient", factory)
    monkeypatch.setattr(planner, "WorkspaceClient", factory)
    monkeypatch.setattr(planner, "workspace_id_of", lambda c: getattr(c, "kw", None) and REMOTE or HUB)
    monkeypatch.setattr(planner, "run", lambda w, out, **k: calls["runs"].append((w, k)) or
                        {"readiness": "READY", "endpoints": 0, "client_references": 0})
    monkeypatch.setattr(planner, "_log", lambda m: calls["logs"].append(m))
    monkeypatch.setattr(store, "ensure_tables", lambda spark, schema: None)
    monkeypatch.setattr(store, "run_exists", lambda *a, **k: False)
    monkeypatch.setattr(store, "upsert", lambda spark, schema, t, cols, key, v: calls["upserts"].append(dict(v)))
    monkeypatch.setattr(store, "write_scan_items", lambda spark, schema, run_id, out: {"workspace_id": None})
    base = {"run_id": "r1", "results_schema": "c.s", "days": "30", "target_catalog": "ai_gateway",
            "target_schema": "migrated", "central_workspaces": REMOTE, "central_client_id": SP_ID,
            "central_secret": "ugmig_scope/sp_secret"}
    widgets.update({k: v for k, v in base.items() if k not in widgets})
    spark = ScanSpark(url)
    exec(compile(NB_PATH.read_text(), str(NB_PATH), "exec"), {"dbutils": dbutils, "spark": spark, "__name__": "t"})
    calls["spark"] = spark
    return calls


def test_scan_notebook_scans_an_allowlisted_workspace_as_the_service_principal(monkeypatch):
    calls = _scan_notebook(monkeypatch, {"target_workspace_id": REMOTE})
    assert calls["clients"] == [{"host": "https://adb-2222222222222222.2.azuredatabricks.net", "client_id": SP_ID,
                                 "client_secret": SECRET_VALUE, "auth_type": "oauth-m2m"}]
    assert calls["secret_reads"] == [("ugmig_scope", "sp_secret")]
    (w, kw), = calls["runs"]
    assert kw["workspace_id"] == REMOTE and kw["remote"] is True
    assert calls["upserts"][0]["workspace_id"] == REMOTE
    assert calls["upserts"][0]["workspace_url"].startswith("https://adb-2222")
    # The URL came from the account table, by ID (a parameter, not text in the query).
    assert any(a == {"id": REMOTE} for _, a in calls["spark"].queries)
    # The secret value is never written to rows or logs.
    assert SECRET_VALUE not in json.dumps(calls["upserts"]) + " ".join(calls["logs"])


def test_scan_notebook_refuses_a_workspace_off_the_allowlist_before_any_call(monkeypatch):
    with pytest.raises(PermissionError, match="allowlist"):
        _scan_notebook(monkeypatch, {"target_workspace_id": OTHER})


def test_scan_notebook_without_a_target_scans_the_hub_as_before(monkeypatch):
    calls = _scan_notebook(monkeypatch, {"target_workspace_id": ""})
    assert calls["clients"] == [] and calls["secret_reads"] == []
    (w, kw), = calls["runs"]
    assert kw["remote"] is False and kw["workspace_id"] is None
    assert calls["upserts"][0]["workspace_id"] == HUB


def test_scan_notebook_needs_a_url_for_the_target(monkeypatch):
    with pytest.raises(ValueError, match="no usable URL"):
        _scan_notebook(monkeypatch, {"target_workspace_id": REMOTE}, url=None)


# ---------- installer ----------

def _installer_helpers():
    import re
    text = (pathlib.Path(__file__).parent / "installer" / "install_template.py").read_text()
    block = re.search(r"# HELPERS-BEGIN\n(.*?)# HELPERS-END", text, re.S).group(1)
    ns: dict = {}
    exec(compile(block, "install_template", "exec"), ns)
    return ns


H = _installer_helpers()


def test_installer_central_mode_is_off_when_blank_and_validated_when_set():
    assert H["central_problems"]("", "", "") == ([], [])
    ids, problems = H["central_problems"](f"{REMOTE}, {OTHER}", "scope/key", SP_ID)
    assert ids == [REMOTE, OTHER] and problems == []
    _, p = H["central_problems"]("adb-1", "scope/key", SP_ID)
    assert any("workspace IDs (numbers)" in x for x in p)
    _, p = H["central_problems"](REMOTE, "scope/key", "")
    assert any("Run jobs as service principal" in x for x in p)
    _, p = H["central_problems"](REMOTE, "not a ref", SP_ID)
    assert any("scope/key" in x for x in p)
    _, p = H["central_problems"]("", "scope/key", SP_ID)
    assert any("no workspaces to manage" in x for x in p)


def test_installer_passes_the_allowlist_identity_and_secret_to_the_scan_and_apply_jobs():
    specs = H["job_specs"]("ug-migration-toolkit", "/Workspace/x", "main.ug", "wh", [], False, "2027-03-30", SP_ID,
                           [REMOTE], "scope/key")
    for role in ("scan", "apply"):
        p = {x.name: x.default for x in specs[role].parameters}
        assert p["central_workspaces"] == REMOTE and p["central_client_id"] == SP_ID, role
        assert p["central_secret"] == "scope/key" and p["target_workspace_id"] == "", role
    assert "central_secret" not in {x.name for x in specs["snapshot"].parameters}
    off = H["job_specs"]("ug-migration-toolkit", "/Workspace/x", "main.ug", "wh", [], False)
    for role in ("scan", "apply"):
        p = {x.name: x.default for x in off[role].parameters}
        assert p["central_workspaces"] == "" and p["central_client_id"] == "" and p["central_secret"] == ""
    env = {e.name: e.value for e in H["app_env"]("main.ug", ["a@x.com"], "0.10.0", [], False, "2027-03-30", [REMOTE], HUB)}
    assert env["UGMIG_CENTRAL_WORKSPACES"] == REMOTE and env["UGMIG_HUB_WORKSPACE_ID"] == HUB
    assert "scope/key" not in json.dumps(env)  # the app never gets the secret reference


# ---------- central_target (both job notebooks) ----------

class TargetSpark:
    def __init__(self, url):
        self.url, self.queries = url, []

    def sql(self, text, args=None):
        self.queries.append((text, args))
        return SimpleNamespace(collect=lambda: [{"workspace_url": self.url}] if self.url else [])


def test_central_target_is_the_hub_without_a_target_and_checks_everything_in_order(monkeypatch):
    hub = SimpleNamespace(config=SimpleNamespace(host="https://hub"))
    reads = []
    monkeypatch.setattr(planner, "workspace_id_of", lambda c: HUB if c is hub else REMOTE)
    get = lambda scope, key: reads.append((scope, key)) or SECRET_VALUE  # noqa: E731
    assert planner.central_target(TargetSpark("x"), hub, "", REMOTE, SP_ID, "s/k", get) == (hub, "", False)
    assert planner.central_target(TargetSpark("x"), hub, HUB, REMOTE, SP_ID, "s/k", get) == (hub, "", False)
    with pytest.raises(PermissionError, match="allowlist"):
        planner.central_target(TargetSpark("x"), hub, OTHER, REMOTE, SP_ID, "s/k", get)
    with pytest.raises(ValueError, match="scope/key"):
        planner.central_target(TargetSpark("x"), hub, REMOTE, REMOTE, SP_ID, "no-slash", get)
    with pytest.raises(ValueError, match="no usable URL"):
        planner.central_target(TargetSpark(""), hub, REMOTE, REMOTE, SP_ID, "s/k", get)
    assert reads == [("s", "k")]  # read only once everything before it passed (the last case reads, then fails on URL)
    made = []
    client, ws, remote = planner.central_target(
        TargetSpark("adb-2.cloud.databricks.com"), hub, REMOTE, REMOTE, SP_ID, "s/k", get,
        factory=lambda **k: made.append(k) or SimpleNamespace(config=SimpleNamespace(host=k["host"])))
    assert (ws, remote) == (REMOTE, True) and made[0]["host"] == "https://adb-2.cloud.databricks.com"
    assert made[0]["client_id"] == SP_ID and made[0]["auth_type"] == "oauth-m2m"


# ---------- the apply notebook ----------

import test_apply as ta  # noqa: E402  (the apply job harness)


def _remote_harness(monkeypatch, scan_ws=None):
    """Patches central_target (unit-tested above) to hand the notebook a separate remote client, and answers the
    scan-workspace lookup. Returns (hub client, remote client, calls to central_target)."""
    hub = ta.CutoverW([])
    remote = ta.CutoverW([], services={ta.SVC: [ta.API_CHAT]})
    remote.config.host = "https://remote.example.com"
    seen = []

    def fake_target(spark, hub_client, target, allow, cid, ref, get, factory=None):
        seen.append(target)
        return (remote, target, True) if target else (hub_client, "", False)

    class Spark(ta.DryRunSpark):
        def sql(self, text, args=None):
            if "ug_migration_scans" in text:
                self.queries.append(text)
                return SimpleNamespace(collect=lambda: [{"workspace_id": scan_ws}] if scan_ws else [])
            return super().sql(text, args)

    monkeypatch.setattr(planner, "central_target", fake_target)
    monkeypatch.setattr(planner, "workspace_id_of", lambda c: HUB)
    monkeypatch.setattr(ta, "DryRunSpark", Spark)
    return hub, remote, seen


def test_apply_notebook_test_call_runs_against_the_remote_workspace(monkeypatch):
    hub, remote, seen = _remote_harness(monkeypatch)
    calls = ta._notebook(monkeypatch, {"apply_id": ta.APPLY, "results_schema": "c.s", "operation": "test_call",
                                       "mode": "dry_run", "services": ta.SVC, "job_run_id": "5",
                                       "target_workspace_id": REMOTE}, hub)
    assert seen == [REMOTE]
    assert calls["items"][ta.APPLY][0]["action"] == "would_test"  # only the remote client has the service
    first = calls["upserts"][0]
    assert first["workspace_id"] == REMOTE
    assert any(u.get("workspace_url") == "https://remote.example.com" for u in calls["upserts"])
    hub_fp = store.legacy_fingerprint({"operation": "test_call", "services": ta.SVC, "rollback_of": "", "force": "false"})
    assert first["fingerprint"] != hub_fp  # a hub dry run can't unlock a remote execute (or the other way round)
    assert first["fingerprint"] == store.legacy_fingerprint(
        {"operation": "test_call", "services": ta.SVC, "rollback_of": "", "force": "false", "target_workspace_id": REMOTE})


def test_apply_notebook_rollback_acts_on_the_workspace_of_the_run_it_undoes(monkeypatch):
    hub, remote, seen = _remote_harness(monkeypatch)
    monkeypatch.setattr(store, "apply_log_from_items", lambda *a, **k: 0)
    src = {"mode": "execute", "operation": "apply", "status": "SUCCEEDED", "job_run_id": "1", "workspace_id": REMOTE}
    rb = ta.rollback_dry_rows(ta.OTHER)
    calls = ta._notebook(monkeypatch, {"apply_id": ta.APPLY, "results_schema": "c.s", "mode": "rollback",
                                       "rollback_of": ta.OTHER, "job_run_id": "5", "dry_run_id": ta.RB_DRY}, hub,
                         apply_rows={ta.OTHER: src}, dry_rows=rb)
    assert seen == [REMOTE] and calls["upserts"][0]["workspace_id"] == REMOTE
    with pytest.raises(ValueError, match="doesn't match"):
        ta._notebook(monkeypatch, {"apply_id": ta.APPLY, "results_schema": "c.s", "mode": "rollback",
                                   "rollback_of": ta.OTHER, "job_run_id": "5", "target_workspace_id": OTHER,
                                   "dry_run_id": ta.RB_DRY}, hub, apply_rows={ta.OTHER: src}, dry_rows=rb)


def test_apply_notebook_refuses_a_scan_of_another_workspace(monkeypatch):
    hub, remote, seen = _remote_harness(monkeypatch, scan_ws=HUB)
    with pytest.raises(ValueError, match="scan of the workspace it changes"):
        ta._notebook(monkeypatch, {"apply_id": ta.APPLY, "results_schema": "c.s", "mode": "dry_run",
                                   "endpoints": "ep1", "target_catalog": "c", "target_schema": "s",
                                   "scan_run_id": ta.OTHER, "target_workspace_id": REMOTE}, hub)
    assert seen == []  # refused before the remote workspace was contacted


def test_apply_notebook_apply_uses_the_remote_client_for_services_and_secrets(monkeypatch):
    import ug_migration_apply as am
    hub, remote, seen = _remote_harness(monkeypatch, scan_ws=REMOTE)
    got = {}

    def fake_apply(w, endpoints, cat, sch, execute, secrets, log_path, **k):
        got["w"], got["secrets_w"] = w, secrets.w
        return []
    monkeypatch.setattr(am, "apply", fake_apply)
    ta._notebook(monkeypatch, {"apply_id": ta.APPLY, "results_schema": "c.s", "mode": "dry_run", "endpoints": "ep1",
                               "target_catalog": "c", "target_schema": "s", "scan_run_id": ta.OTHER,
                               "target_workspace_id": REMOTE, "create_uc_secrets": "true",
                               "uc_secret_map": '{"sc/k": "secrets/c.s.k"}', "secret_schemas": "c.s"}, hub)
    # Services, providers and created UC secrets go through the remote workspace; its secret scopes are read there.
    assert got["w"] is remote and got["secrets_w"] is remote


def test_fingerprints_tell_workspaces_apart_and_keep_hub_runs_as_before():
    base = {"scan_run_id": "s", "endpoints": "a", "target_catalog": "c", "target_schema": "d"}
    assert store.selection_fingerprint(base) == store.selection_fingerprint({**base, "target_workspace_id": ""})
    assert store.selection_fingerprint(base) != store.selection_fingerprint({**base, "target_workspace_id": REMOTE})


# ---------- app ----------

from test_app import OP, SCAN, env  # noqa: E402,F401  (the app fixture and its constants)
from app.backend import main  # noqa: E402


@pytest.fixture
def central(env, monkeypatch):
    monkeypatch.setattr(main, "CENTRAL_WORKSPACES", [REMOTE])
    monkeypatch.setattr(main, "_HUB_ID", {"id": HUB})
    return env


def test_config_reports_central_mode(central):
    c = central.client.get("/api/config").json()["central"]
    assert c == {"enabled": True, "workspaces": [REMOTE], "hub_workspace_id": HUB}
    ws = central.client.get("/api/workspaces").json()
    assert ws["central"] is True and [w["workspace_id"] for w in ws["workspaces"]] == [HUB, REMOTE]
    assert ws["workspaces"][0]["hub"] is True


def test_config_without_central_mode_is_as_before(env):
    assert env.client.get("/api/config").json()["central"] == {"enabled": False, "workspaces": [],
                                                                 "hub_workspace_id": None}


def test_scan_start_names_an_allowlisted_workspace_only(central):
    r = central.client.post("/api/scans", json={"days": 30, "target_workspace_id": REMOTE}, headers=OP)
    assert r.status_code == 200
    params = central.sdk.jobs.run_now.call_args.kwargs["job_parameters"]
    assert params["target_workspace_id"] == REMOTE
    assert not {"central_workspaces", "central_secret", "central_client_id"} & set(params)  # fixed in the job
    bad = central.client.post("/api/scans", json={"days": 30, "target_workspace_id": OTHER}, headers=OP)
    assert bad.status_code == 400 and "isn't one this app may scan" in bad.json()["detail"]


def test_scan_start_for_the_hub_sends_no_target(central):
    central.client.post("/api/scans", json={"days": 30, "target_workspace_id": HUB}, headers=OP)
    assert "target_workspace_id" not in central.sdk.jobs.run_now.call_args.kwargs["job_parameters"]


def test_apply_and_cutover_act_on_the_scans_allowlisted_workspace(central):
    central.store["scans"][0]["workspace_id"] = REMOTE
    r = central.client.post("/api/applies", json={"mode": "dry_run", "scan_run_id": SCAN, "endpoints": ["ep1"],
                                                  "target_catalog": "c", "target_schema": "s"}, headers=OP)
    assert r.status_code == 200, r.text
    assert central.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["target_workspace_id"] == REMOTE
    c = central.client.post("/api/cutover", json={"operation": "test_call", "mode": "dry_run", "scan_run_id": SCAN,
                                                  "services": ["system.ai.gpt-5-mini"]}, headers=OP)
    assert c.status_code == 200, c.text
    assert central.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["target_workspace_id"] == REMOTE


def test_changes_refuse_a_workspace_off_the_allowlist_and_send_no_target_for_the_hub(central):
    central.store["scans"][0]["workspace_id"] = OTHER
    r = central.client.post("/api/applies", json={"mode": "dry_run", "scan_run_id": SCAN, "endpoints": ["ep1"],
                                                  "target_catalog": "c", "target_schema": "s"}, headers=OP)
    assert r.status_code == 409 and "allowlist" in r.json()["detail"]
    central.store["scans"][0]["workspace_id"] = HUB
    r = central.client.post("/api/applies", json={"mode": "dry_run", "scan_run_id": SCAN, "endpoints": ["ep1"],
                                                  "target_catalog": "c", "target_schema": "s"}, headers=OP)
    assert r.status_code == 200 and central.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["target_workspace_id"] == ""


def test_rollback_targets_the_workspace_of_the_execute_run(central):
    from test_app import EXEC, _execute_row
    row = _execute_row()
    row["workspace_id"] = REMOTE
    central.store["applies"].append(row)
    from test_app import ROLLBACK_BODY, _rollback_dry_row
    central.store["applies"].append(_rollback_dry_row())
    r = central.client.post("/api/applies", json=ROLLBACK_BODY, headers=OP)
    assert r.status_code == 200, r.text
    assert central.sdk.jobs.run_now.call_args.kwargs["job_parameters"]["target_workspace_id"] == REMOTE


def test_run_lists_show_and_filter_by_workspace(central):
    central.store["applies"][0]["workspace_id"] = REMOTE
    rows = central.client.get("/api/applies", headers=OP).json()
    assert {r["workspace_id"] for r in rows} == {REMOTE}
    assert central.client.get(f"/api/applies?workspace_id={HUB}", headers=OP).json() == []
    assert len(central.client.get(f"/api/applies?workspace_id={REMOTE}", headers=OP).json()) == 1


def test_scans_list_can_filter_by_workspace(central):
    assert central.client.get(f"/api/scans?workspace_id={REMOTE}").status_code == 200
    assert central.client.get("/api/scans?workspace_id=adb-1").status_code == 400


def test_changes_fail_closed_when_the_scan_or_hub_workspace_is_unknown(central, monkeypatch):
    body = {"mode": "dry_run", "scan_run_id": SCAN, "endpoints": ["ep1"], "target_catalog": "c", "target_schema": "s"}
    central.store["scans"][0]["workspace_id"] = None  # a scan that doesn't record its workspace isn't the hub
    r = central.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 409 and "Scan the workspace again" in r.json()["detail"]
    central.store["scans"][0]["workspace_id"] = HUB
    monkeypatch.setattr(main, "_HUB_ID", {"id": ""})
    monkeypatch.setattr(main.planner, "workspace_id_of", lambda c: (_ for _ in ()).throw(RuntimeError("down")))
    r = central.client.post("/api/applies", json=body, headers=OP)
    assert r.status_code == 503 and "which workspace this app runs in" in r.json()["detail"]
    central.sdk.jobs.run_now.assert_not_called()


def test_apply_notebook_refuses_a_scan_without_a_workspace_in_central_mode(monkeypatch):
    hub, remote, seen = _remote_harness(monkeypatch, scan_ws="")
    with pytest.raises(ValueError, match="doesn't record its workspace"):
        ta._notebook(monkeypatch, {"apply_id": ta.APPLY, "results_schema": "c.s", "mode": "dry_run",
                                   "operation": "pause_legacy", "endpoints": "ep1", "scan_run_id": ta.OTHER,
                                   "central_workspaces": REMOTE}, hub)
    assert seen == []
