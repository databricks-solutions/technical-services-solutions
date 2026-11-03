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


def test_installer_passes_the_allowlist_identity_and_secret_to_the_scan_job_only():
    specs = H["job_specs"]("ug-migration-toolkit", "/Workspace/x", "main.ug", "wh", [], False, "2027-03-30", SP_ID,
                           [REMOTE], "scope/key")
    scan = {p.name: p.default for p in specs["scan"].parameters}
    assert scan["central_workspaces"] == REMOTE and scan["central_client_id"] == SP_ID
    assert scan["central_secret"] == "scope/key" and scan["target_workspace_id"] == ""
    assert "central_secret" not in {p.name for p in specs["apply"].parameters}
    off = H["job_specs"]("ug-migration-toolkit", "/Workspace/x", "main.ug", "wh", [], False)
    off_scan = {p.name: p.default for p in off["scan"].parameters}
    assert off_scan["central_workspaces"] == "" and off_scan["central_client_id"] == "" and off_scan["central_secret"] == ""
    env = {e.name: e.value for e in H["app_env"]("main.ug", ["a@x.com"], "0.10.0", [], False, "2027-03-30", [REMOTE], HUB)}
    assert env["UGMIG_CENTRAL_WORKSPACES"] == REMOTE and env["UGMIG_HUB_WORKSPACE_ID"] == HUB
    assert "scope/key" not in json.dumps(env)  # the app never gets the secret reference


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


def test_apply_and_cutover_refuse_a_scan_of_another_workspace(central):
    central.store["scans"][0]["workspace_id"] = REMOTE
    r = central.client.post("/api/applies", json={"mode": "dry_run", "scan_run_id": SCAN, "endpoints": ["ep1"]},
                            headers=OP)
    assert r.status_code == 409 and "only in the hub workspace" in r.json()["detail"]
    c = central.client.post("/api/cutover", json={"operation": "test_call", "mode": "dry_run", "scan_run_id": SCAN,
                                                  "services": ["system.ai.gpt-5-mini"]}, headers=OP)
    assert c.status_code == 409 and "only in the hub workspace" in c.json()["detail"]


def test_scans_list_can_filter_by_workspace(central):
    assert central.client.get(f"/api/scans?workspace_id={REMOTE}").status_code == 200
    assert central.client.get("/api/scans?workspace_id=adb-1").status_code == 400
