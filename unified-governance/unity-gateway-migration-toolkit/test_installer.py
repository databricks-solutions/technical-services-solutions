"""Offline tests for the installer notebook.

installer/install_template.py has two layers. The HELPERS block (between the HELPERS-BEGIN / HELPERS-END markers) is pure
and is tested directly. The rest of the notebook runs against FakeWS, an in-memory workspace: the tests build the notebook
the way make_installer.build does (a small test payload instead of the real files), then run its cells one by one, with
dbutils, spark, displayHTML and the Databricks SDK replaced by fakes. Nothing here talks to a workspace.
"""

import base64
import dataclasses
import io
import json
import pathlib
import re
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

import databricks.sdk as sdk_pkg
import make_installer
import pytest
import ug_migration_apply as apply_mod
from databricks.sdk import errors as sdk_errors
from databricks.sdk.service import apps, jobs

TEMPLATE = pathlib.Path(__file__).parent / "installer" / "install_template.py"
TEXT = TEMPLATE.read_text()


def _helpers() -> dict:
    block = re.search(r"# HELPERS-BEGIN\n(.*?)# HELPERS-END", TEXT, re.S).group(1)
    ns: dict = {}
    exec(compile(block, str(TEMPLATE), "exec"), ns)
    return ns


H = _helpers()

ME = "admin@example.com"
FOLDER = f"/Workspace/Users/{ME}/ug-migration-toolkit"  # the default install folder
APP = "ug-migration-toolkit"
DESC = "Unity Gateway Migration Toolkit: account overview, workspace scans, readiness, code fixes and apply"
WH_ID = "0a1b2c3d"
WH_LABEL = f"serverless ({WH_ID})"
A1 = "aaaaaaaa-0000-0000-0000-000000000001"  # older apply run
A2 = "aaaaaaaa-0000-0000-0000-000000000002"  # newer apply run
RUN1, RUN2 = "900001", "900002"  # their job run ids
RESULT_TABLES = ("scans", "scan_items", "applies", "apply_items", "workspaces", "endpoints")


# ---------------------------------------------------------------------------------------------------------------------
# Pure helpers

@pytest.mark.parametrize("path", [
    "/Workspace/Users/someone@example.com/unity-gateway-migration-toolkit",
    "/Workspace/Users/someone/x/y",
    "/Workspace/Shared/ug toolkit",
])
def test_valid_folder(path):
    assert H["valid_folder"](path) is None


@pytest.mark.parametrize("path", [
    "/Workspace/Users/someone",                   # the home folder itself
    "/Workspace/Users/someone/",                  # the home folder itself
    "/Workspace/Shared",                          # the Shared root
    "/Users/someone/x",                           # not under /Workspace
    "/Workspace/Repos/x",                         # other top-level folder
    "/Workspace/Users/someone/../../Shared",      # traversal
    "/Workspace/Users/someone/./x",               # dot segment
    "/Workspace/Users/.hidden/x",                 # hidden segment
    "/Workspace/Users//x",                        # empty segment
])
def test_invalid_folder(path):
    assert H["valid_folder"](path) is not None


def test_folder_and_schema_defaults():
    assert H["folder_for"]("", "a@b.c", "ug-migration-toolkit") == "/Workspace/Users/a@b.c/ug-migration-toolkit"
    assert H["folder_for"]("", "a@b.c", "team-a") == "/Workspace/Users/a@b.c/team-a-toolkit"
    assert H["folder_for"]("/Workspace/Shared/x/", "a@b.c", "app") == "/Workspace/Shared/x"
    assert H["results_schema_for"]("", "ug-migration-toolkit") == "ug_migration"
    assert H["results_schema_for"]("", "unity-gateway-migration") == "ug_migration"
    assert H["results_schema_for"]("", "ug-migration-bundle") == "ug_migration_bundle"
    assert H["results_schema_for"]("my_schema", "ug-migration-bundle") == "my_schema"


def test_valid_app_name():
    assert H["valid_app_name"]("ug-migration-toolkit")
    assert H["valid_app_name"]("ab")
    assert not H["valid_app_name"]("a")                    # too short
    assert not H["valid_app_name"]("x" * 31)               # too long
    assert not H["valid_app_name"]("UG-Migration")         # uppercase
    assert not H["valid_app_name"]("ug_migration")         # underscore


def test_service_principal_detection():
    assert H["is_service_principal"]("0b1f7c2e-1234-4abc-9def-0123456789ab")
    assert not H["is_service_principal"]("someone@example.com")
    assert not H["is_service_principal"]("")


def test_downgrade_needs_setting_and_compares_numbers():
    assert H["downgrade_problem"]("0.8.0", "0.7.0", allow=False) is not None
    assert H["downgrade_problem"]("0.8.0", "0.7.0", allow=True) is None
    assert H["downgrade_problem"]("0.7.0", "0.8.0", allow=False) is None
    assert H["downgrade_problem"]("", "0.8.0", allow=False) is None
    assert H["downgrade_problem"]("0.10.0", "0.9.0", allow=False) is not None
    assert "allow_downgrade" in H["downgrade_problem"]("0.8.0", "0.7.0", allow=False)


def test_marker_status():
    text = H["marker_text"](APP, "0.9.0", "main.ug_migration", FOLDER, "a")
    assert H["marker_status"](text, APP) == ("ours", APP)
    assert H["marker_status"](text, "other-app") == ("other", APP)
    assert H["marker_status"]("Unity Gateway migration toolkit\n", APP) == ("ours", "")  # 0.7 and 0.8 plain marker
    assert H["marker_status"](None, APP) == ("missing", "")
    assert H["marker_status"]("some other file", APP)[0] == "other"


def test_toolkit_app_marker():
    assert H["is_toolkit_app"](DESC)
    assert not H["is_toolkit_app"]("my own app")
    assert not H["is_toolkit_app"](None)


def test_jobs_without_app_tag_are_not_named_installs():
    assert H["app_from_job"]("[ug-migration-toolkit] Unity Gateway migration apply", {"app": "ug-migration-toolkit"}) == \
        "ug-migration-toolkit"
    # A bundle deploy in dev: the name has a target prefix and there is no app tag. It must not become an app name.
    assert H["app_from_job"]("[dev admin] Unity Gateway migration apply", {}) == ""
    assert H["bundle_made"]("[dev admin] Unity Gateway migration apply", "ug-migration-bundle")
    assert not H["bundle_made"]("[ug-migration-toolkit] Unity Gateway migration apply", "ug-migration-toolkit")


def test_install_names_lists_only_valid_names():
    installs = [{"app": "dev admin"}, {"app": "ug-migration-toolkit"}, {"app": ""}]
    assert H["install_names"](installs, ["ug-migration-bundle", "bad name"]) == ["ug-migration-bundle", "ug-migration-toolkit"]


def test_secret_schemas():
    assert H["parse_secret_schemas"]("") == ([], None)
    assert H["parse_secret_schemas"]("main.sec, main.sec ,other.s") == (["main.sec", "other.s"], None)
    _, problem = H["parse_secret_schemas"]("main")
    assert problem and "catalog.schema" in problem


def test_shared_state_finds_results_and_folder_clashes():
    others = [
        {"app": "ug-migration", "results": "MAIN.ug_migration", "folder": "/Workspace/Users/a/ug-migration-toolkit"},
        {"app": "other", "results": "main.other", "folder": "/Workspace/Users/a/ug-migration-toolkit/sub"},
        {"app": "clean", "results": "main.clean", "folder": "/Workspace/Users/a/clean"},
    ]
    clash = H["shared_state"](others, "main.ug_migration", "/Workspace/Users/a/ug-migration-toolkit")
    assert {"kind": "results", "app": "ug-migration"} in clash
    assert {"kind": "folder", "app": "ug-migration"} in clash
    assert {"kind": "folder", "app": "other"} in clash
    assert not any(c["app"] == "clean" for c in clash)


def test_job_specs_names_tags_and_parameter_contract():
    specs = H["job_specs"](APP, FOLDER, "main.ug_migration", WH_ID, ["main.s"], True)
    assert set(specs) == {"snapshot", "scan", "apply"}
    titles = {"snapshot": "snapshot", "scan": "workspace scan", "apply": "apply"}
    for role, spec in specs.items():
        assert spec.name == f"[{APP}] Unity Gateway migration {titles[role]}"
        assert spec.tags == {"tool": "ug-migration-toolkit", "Project": "unity-gateway-migration-toolkit",
                             "app": APP, "role": role}
    params = {p.name: p.default for p in specs["apply"].parameters}
    assert params["grants"] == "false"                       # the app passes grants explicitly; the job default is off
    assert params["smoke_test"] == "false" and params["force"] == "false"
    assert params["secret_schemas"] == "main.s" and params["allow_secret_read_enabled"] == "true"
    assert params["ack_guardrails"] == "false"
    snap = {p.name: p.default for p in specs["snapshot"].parameters}
    assert snap["deep_wave"] == "" and snap["deep_warehouse_id"] == WH_ID
    assert snap["snapshot_table"] == "main.ug_migration.ug_migration"
    assert specs["snapshot"].schedule.pause_status == jobs.PauseStatus.PAUSED
    scan = {p.name: p.default for p in specs["scan"].parameters}
    assert (scan["target_catalog"], scan["target_schema"]) == ("ai_gateway", "migrated")


def test_app_update_keeps_fields_the_installer_does_not_set():
    existing = apps.App(name=APP, description="Unity Gateway Migration Toolkit: x", budget_policy_id="bp-1",
                        compute_size=apps.ComputeSize.MEDIUM, compute_min_instances=1, space="team-space",
                        url="https://example/app", id="app-id", active_deployment=apps.AppDeployment(deployment_id="d1"),
                        resources=[], user_api_scopes=["sql"])
    spec = H["app_update_spec"](existing, name=APP, description="new", resources=[], user_api_scopes=["sql"])
    assert spec.budget_policy_id == "bp-1" and spec.compute_size == apps.ComputeSize.MEDIUM
    assert spec.compute_min_instances == 1 and spec.space == "team-space" and spec.description == "new"
    assert spec.url is None and spec.id is None and spec.active_deployment is None


def test_app_env_and_resources():
    env = {e.name: e for e in H["app_env"]("main.ug_migration", ["a@x.com"], "0.9.0", ["main.s"], False)}
    assert env["UGMIG_VERSION"].value == "0.9.0" and env["UGMIG_ALLOW_SECRET_READ"].value == "false"
    assert env["OPERATORS"].value == "a@x.com" and env["UGMIG_MAX_SCAN_AGE_DAYS"].value == "14"
    res = H["app_resources"](WH_ID, {"snapshot": 1, "scan": 2, "apply": 3})
    assert {r.name for r in res} == {"sql-warehouse", "snapshot-job", "scan-job", "apply-job"}


def _pending():
    return [{"apply_id": A2, "created": 1}, {"apply_id": A1, "created": 2}]  # newest first


def test_uninstall_plan_matrix():
    logs = {A1, A2}
    # Services rolled back: removed first, nothing to warn about.
    remove, keep, problems, warnings = H["uninstall_plan"](True, True, True, _pending(), logs, [], "c.s", FOLDER, True)
    assert problems == [] and warnings == [] and remove[0].startswith("Unity Gateway services")
    # Services kept with the tables dropped: allowed with logs kept, warned, with the rollback command for each run.
    remove, keep, problems, warnings = H["uninstall_plan"](True, False, False, _pending(), logs, [], "c.s", FOLDER, True)
    assert problems == []
    assert any("WARNING" not in w and "rollback" in w for w in warnings) and any(A1 in w for w in warnings)
    assert any("apply_logs" in k for k in keep)
    # Services kept and the logs removed: refused (the services would be orphaned).
    _, _, problems, _ = H["uninstall_plan"](True, True, False, _pending(), logs, [], "c.s", FOLDER, True)
    assert any("apply logs are needed" in p for p in problems)
    _, _, problems, _ = H["uninstall_plan"](False, True, False, _pending(), logs, [], "c.s", FOLDER, True)
    assert any("apply logs are needed" in p for p in problems)
    # Tables dropped with a run that has no log: refused (no way to roll it back later).
    _, _, problems, _ = H["uninstall_plan"](True, False, False, _pending(), {A2}, [], "c.s", FOLDER, True)
    assert any(A1 in p and "no apply log" in p for p in problems)
    # Tables kept: services kept, nothing to refuse.
    _, keep, problems, _ = H["uninstall_plan"](False, False, False, _pending(), logs, [], "c.s", FOLDER, True)
    assert problems == [] and any("results tables in c.s" in k for k in keep)
    # Unmatched applies in the schema: dropping the tables is refused.
    _, _, problems, _ = H["uninstall_plan"](True, False, False, [], set(), [{"apply_id": A1}], "c.s", FOLDER, True)
    assert any("aren't this install's" in p for p in problems)
    # No marker for this app: the files stay.
    remove, keep, _, _ = H["uninstall_plan"](False, False, False, [], set(), [], "c.s", FOLDER, False)
    assert not any(FOLDER in r for r in remove) and any("nothing in that folder" in k for k in keep)


def test_progress_decision():
    d = H["progress_decision"]
    assert d(2, 0, 1, 3) == "done"
    assert d(2, 1, 1, 3) == "again"
    assert d(2, 2, 1, 3) == "stuck"
    assert d(2, 1, 3, 3) == "limit"


def test_rollback_and_system_fix_messages():
    assert H["rollback_command"](FOLDER, A1).startswith("python ug_migration_apply.py --profile <profile> rollback --log")
    assert f"{FOLDER}/apply_logs/{A1}.jsonl" in H["rollback_command"](FOLDER, A1)
    fix = H["system_table_fix"](["system.serving"], ME)
    assert "GRANT USE SCHEMA, SELECT ON SCHEMA system.serving" in fix and "GRANT USE CATALOG ON CATALOG system" in fix
    assert H["create_schema_fix"]("main", "admins", ME) == (
        f"Ask the owner of catalog main (admins) to run: GRANT USE CATALOG, CREATE SCHEMA ON CATALOG `main` TO `{ME}`")
    lines = H["target_schema_lines"]("main.ug_migrated", ME)
    assert lines == ["CREATE SCHEMA IF NOT EXISTS `main`.`ug_migrated`;", f"GRANT USE CATALOG ON CATALOG `main` TO `{ME}`;",
                     f"GRANT USE SCHEMA, CREATE SERVICE ON SCHEMA `main`.`ug_migrated` TO `{ME}`;"]


def test_schema_comment_marks_toolkit_schema():
    assert H["schema_made_by_toolkit"](f"Unity Gateway migration app results (app: {APP})", APP)
    assert not H["schema_made_by_toolkit"]("my team's schema", APP)
    assert not H["schema_made_by_toolkit"](None, APP)


def test_bundle_yaml_operators_have_no_default_for_prod():
    """prod must not default operators to the deploying identity (a service principal UUID): no default, per target."""
    bundle = (pathlib.Path(__file__).parent / "databricks.yml").read_text()
    top = re.search(r"\nvariables:\n(.*?)\n(?=\S)", "\n" + bundle + "\nEND", re.S).group(1)
    block = re.search(r"\n  operators:\n((?:    .*\n|\n)*)", "\n" + top + "\n").group(1)
    assert "default:" not in block
    prod = re.search(r"\n  prod:\n((?:    .*\n|\n)*)", bundle).group(1)
    assert not re.search(r"^\s+operators:", prod, re.M)  # the prod target sets nothing: --var operators is required


def test_the_deployed_app_gets_the_modules_it_imports(tmp_path):
    """main.py imports the store, apply and planner modules. The installer deploys {FILES}/app, so its zip carries
    them under app/backend too (byte-equal to the root files); the bundle deploys the app from its root."""
    import sys
    root = pathlib.Path(__file__).parent
    sys.path.insert(0, str(root))
    import make_installer
    built = pathlib.Path(make_installer.build(str(tmp_path), check_fresh=False)).read_text()
    payload = re.search(r'^PAYLOAD = "([^"]+)"', built, re.M).group(1)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload))) as z:
        names = set(z.namelist())
        for m in make_installer.APP_MODULES:
            assert f"app/backend/{m}" in names and m in names
            assert z.read(f"app/backend/{m}") == (root / m).read_bytes()
    bundle = (root / "databricks.yml").read_text()
    assert re.search(r"^\s+source_code_path: \.$", bundle, re.M)
    assert '"app.backend.main:app"' in bundle
    assert "-r app/requirements.txt" in (root / "requirements.txt").read_text()


# ---------------------------------------------------------------------------------------------------------------------
# Notebook-level tests: the generated notebook run cell by cell against FakeWS

class NBExit(Exception):
    pass


class FakeRun:
    def __init__(self, run_id, behaviour="SUCCEEDED", ws=None):
        self.run_id = run_id
        self.behaviour = behaviour
        self.ws = ws

    def result(self, timeout=None):
        if self.behaviour == "TIMEOUT":
            raise TimeoutError("timed out after 1:00:00")
        if self.behaviour == "FAILED":
            raise sdk_errors.OperationFailed("job failed")
        return SimpleNamespace(state="SUCCESS")


def _ns(**kw):
    return SimpleNamespace(**kw)


def _state(value):
    return _ns(value=value)


class FakeWS:
    """In-memory workspace. Tests set up the state and read back what the notebook did."""

    def __init__(self, me=ME):
        self.me = me
        self.warehouses = {WH_ID: {"name": "serverless", "state": "RUNNING"}}
        self.start_fails = False
        self.catalogs = {"main": "admins", "other": "admins"}
        self.schemas = {}  # "c.s" -> {"owner", "comment"}
        self.tables = {}  # "c.s.t" -> list of rows
        self.no_create = set()  # catalogs where CREATE SCHEMA is refused
        self.denied = set()  # system tables the warehouse can't read
        self.held = set()  # (securable, name, privilege) held by me
        self.apps = {}
        self.deleting_polls = 0  # after an app delete, get_app shows it as DELETING this many times
        self.pending_delete = {}
        self.jobs = {}  # id -> JobSettings
        self.next_job = 100
        self.runs = {}  # job id -> [run ids] (history)
        self.active = set()  # job ids with an active run
        self.files = {}
        self.dirs = set()
        self.rollback_script = {}  # apply id -> statuses, one per rollback run ("SUCCEEDED" when empty)
        # apply id -> (status, summary) per rollback dry run; default SUCCEEDED with one object to delete
        self.dry_script = {}
        # apply id -> the summary a NEEDS_ATTENTION rollback of it stores; by default one kept object that nothing else
        # explains, so the run stays pending (the app's rule: ug_migration_store.rollback_done)
        self.rollback_summary = {}
        self.trashed = []
        self.log = []
        self.next_run = 500
        self.clock = 0
        self.sp_rules = None  # grant rules on the run-as SP's rule set; None = the API isn't reachable
        self.current_catalog = "main"  # the workspace's default catalog (SELECT current_catalog())
        self.secret_scopes = {"s": {"k"}}  # scope -> keys
        self.secret_acls = {("s", SP_ID): "READ"}  # (scope, principal) -> permission
        self.sps = [("ugmig-central", SP_ID)]  # service principals in the workspace: (display name, application ID)

    # ---- seeding helpers
    def add_table(self, key, rows=()):
        self.tables[key] = list(rows)

    # ---- SQL emulation (spark.sql) on the results tables
    def sql(self, stmt, args=None):
        s = " ".join(stmt.split())
        self.log.append(("sql", s[:100]))
        rows = []
        if s == "SELECT current_catalog()":
            rows = [(self.current_catalog,)]
        if "FROM system.access.workspaces_latest" in s:
            rows = [("acct-1",)]
        m = re.match(r"DROP TABLE IF EXISTS `(\w+)`\.`(\w+)`\.ug_migration_(\w+)", s)
        if m:
            self.tables.pop(f"{m[1]}.{m[2]}.ug_migration_{m[3]}", None)
        m = re.match(r"DROP SCHEMA IF EXISTS `(\w+)`\.`(\w+)` RESTRICT", s)
        if m:
            full = f"{m[1]}.{m[2]}"
            if any(k.startswith(full + ".") for k in self.tables):
                raise Exception("[SCHEMA_NOT_EMPTY] cannot drop")
            self.schemas.pop(full, None)
        m = re.match(r"CREATE SCHEMA IF NOT EXISTS `(\w+)`\.`(\w+)`", s)
        if m:
            self.schemas.setdefault(f"{m[1]}.{m[2]}", {"owner": self.me, "comment": ""})
        if "ug_migration_applies a" in s:  # pending executes
            m = re.search(r"FROM `(\w+)`\.`(\w+)`\.ug_migration_applies a", s)
            full = f"{m[1]}.{m[2]}"
            if full not in self.schemas:
                raise Exception("[SCHEMA_NOT_FOUND] The schema does not exist")
            applies = self.tables.get(f"{full}.ug_migration_applies")
            if applies is None:
                raise Exception("[TABLE_OR_VIEW_NOT_FOUND] The table or view does not exist")
            items = self.tables.get(f"{full}.ug_migration_apply_items", [])
            # Every execute run: the installer decides which ones are rolled back from the rollback rows (below).
            for a in sorted(applies, key=lambda r: r["started_at"], reverse=True):
                if a["mode"] != "execute":
                    continue
                created = sum(1 for i in items if i["apply_id"] == a["apply_id"] and '"created"' in i["payload"])
                rows.append({"apply_id": a["apply_id"], "job_run_id": a["job_run_id"], "created": created})
        if s.startswith("SELECT rollback_of, status, summary FROM"):  # the rollback rows, as the app stores them
            full = self.results_schema()
            if f"{full}.ug_migration_applies" not in self.tables:
                raise Exception("[TABLE_OR_VIEW_NOT_FOUND] The table or view does not exist")
            rows = [{"rollback_of": r["rollback_of"], "status": r["status"], "summary": r.get("summary", "{}")}
                    for r in self.tables[f"{full}.ug_migration_applies"]
                    if r["mode"] == "rollback" and r.get("rollback_of")]
        if re.search(r"SELECT status FROM .*ug_migration_applies WHERE apply_id = :id$", s):
            assert args and set(args) == {"id"}  # one run's row, by the apply_id the installer gave it, bound
            hits = [r for r in self.tables.get(f"{self.results_schema()}.ug_migration_applies", [])
                    if r["apply_id"] == args["id"]]
            rows = [{"status": hits[-1]["status"]}] if hits else []
        return _ns(collect=lambda: rows)

    def results_schema(self):
        return "main.ug_migration"

    def _now(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def _rollback_row(self, apply_id, status, row_id=None, **extra):
        self.clock += 1
        summary = self.rollback_summary.get(apply_id, {"kept": 1, "kept_other_run": 0, "kept_preexisting": 0}) \
            if status == "NEEDS_ATTENTION" else {}
        self.tables.setdefault(f"main.ug_migration.ug_migration_applies", []).append(
            {"apply_id": row_id or f"rb-{self.clock}", "mode": "rollback", "rollback_of": apply_id, "status": status,
             "summary": json.dumps(summary), "started_at": self._now(), **extra})
        if status == "SUCCEEDED":
            for r in self.tables.get("main.ug_migration.ug_migration_apply_items", []):
                if r["apply_id"] == apply_id:
                    r["payload"] = '{"action": "rolled_back"}'

    # ---- the SDK surface the notebook uses
    def make(self):
        ws = self

        class Current:
            def me(self_inner):
                return _ns(user_name=ws.me, groups=[])

        class Catalogs:
            def list(self_inner):
                return [_ns(name=n) for n in ws.catalogs]

            def get(self_inner, name):
                if name not in ws.catalogs:
                    raise sdk_errors.NotFound(f"catalog {name} does not exist")
                return _ns(name=name, owner=ws.catalogs[name])

        class Schemas:
            def get(self_inner, full):
                if full not in ws.schemas:
                    raise sdk_errors.NotFound(f"schema {full} does not exist")
                s = ws.schemas[full]
                return _ns(full_name=full, owner=s["owner"], comment=s["comment"])

        class Warehouses:
            def _obj(self_inner, wid):
                s = ws.warehouses[wid]
                return _ns(id=wid, name=s["name"], state=_state(s["state"]))

            def list(self_inner):
                return [self_inner._obj(k) for k in ws.warehouses]

            def get(self_inner, wid):
                if wid not in ws.warehouses:
                    raise sdk_errors.NotFound("warehouse not found")
                return self_inner._obj(wid)

            def start_and_wait(self_inner, wid, timeout=None):
                ws.log.append(("start_warehouse", wid))
                if ws.start_fails:
                    raise RuntimeError("warehouse failed to start")
                ws.warehouses[wid]["state"] = "RUNNING"
                return self_inner._obj(wid)

        class Grants:
            def get_effective(self_inner, securable, name, principal=None):
                privs = [_ns(privilege=_ns(value=p)) for (t, n, p) in ws.held if t == securable and n == name]
                return _ns(privilege_assignments=[_ns(privileges=privs)] if privs else [])

        class Statements:
            def execute_statement(self_inner, statement, warehouse_id, wait_timeout):
                s = " ".join(statement.split())
                ws.log.append(("sql_warehouse", s[:80]))
                err = None
                m = re.match(r"SELECT 1 FROM (\S+) LIMIT 1", s)
                if m and m[1] in ws.denied:
                    err = f"[INSUFFICIENT_PERMISSIONS] User does not have SELECT on table '{m[1]}'"
                m = re.match(r"CREATE SCHEMA IF NOT EXISTS `(\w+)`\.`(\w+)`(?: COMMENT '(.*)')?", s)
                if m:
                    if m[1] in ws.no_create:
                        err = f"[INSUFFICIENT_PERMISSIONS] User does not have CREATE SCHEMA on Catalog '{m[1]}'"
                    elif m[1] not in ws.catalogs:
                        err = f"[NO_SUCH_CATALOG_EXCEPTION] Catalog '{m[1]}' was not found"
                    else:
                        ws.schemas.setdefault(f"{m[1]}.{m[2]}", {"owner": ws.me, "comment": m[3] or ""})
                if err:
                    return _ns(status=_ns(state=_state("FAILED"), error=_ns(message=err)))
                return _ns(status=_ns(state=_state("SUCCEEDED"), error=None))

        class Workspace:
            def _children(self_inner, path):
                kids = {p for p in list(ws.files) + list(ws.dirs) if p.startswith(path + "/")}
                return sorted({path + "/" + p[len(path) + 1:].split("/")[0] for p in kids})

            def list(self_inner, path):
                kids = self_inner._children(path)
                if path not in ws.dirs and not kids:
                    raise sdk_errors.NotFound(path)
                return [_ns(path=k) for k in kids]

            def get_status(self_inner, path):
                if path in ws.files or path in ws.dirs:
                    return _ns(path=path, resource_id=None, object_id=abs(hash(path)) % 10**9)
                raise sdk_errors.NotFound(path)

            def update_permissions(self_inner, workspace_object_type, workspace_object_id, access_control_list=None):
                ws.permission_updates = getattr(ws, "permission_updates", []) + [
                    (workspace_object_type, workspace_object_id, access_control_list)]

            def export(self_inner, path, format=None):
                if path not in ws.files:
                    raise sdk_errors.NotFound(path)
                if format is not None and getattr(format, "value", format) == "RAW":
                    # Like the real API: workspace FILEs can't be exported as RAW (seen live 2026-10-31).
                    raise sdk_errors.BadRequest(f"Exporting a FILE asset at {path} in RAW format is not supported.")
                return _ns(content=base64.b64encode(ws.files[path]).decode())

            def download(self_inner, path, format=None):
                if path not in ws.files:
                    raise sdk_errors.NotFound(path)
                return io.BytesIO(ws.files[path])

            def upload(self_inner, path, data, format=None, language=None, overwrite=False):
                ws.files[path] = data.read()
                ws.log.append(("upload", path))

            def mkdirs(self_inner, path):
                parts = path.split("/")
                for i in range(2, len(parts) + 1):
                    ws.dirs.add("/".join(parts[:i]))

            def delete(self_inner, path, recursive=False):
                hit = [p for p in list(ws.files) if p == path or p.startswith(path + "/")]
                dirs = [d for d in list(ws.dirs) if d == path or d.startswith(path + "/")]
                if not hit and not dirs:
                    raise sdk_errors.NotFound(path)
                for p in hit:
                    del ws.files[p]
                for d in dirs:
                    ws.dirs.discard(d)
                ws.log.append(("delete_path", path))

        class Lakeview:
            def trash(self_inner, dash):
                ws.trashed.append(dash)

        class Jobs:
            def list(self_inner, expand_tasks=False):
                # Like the real list API: no parameters and no run-as (only jobs.get has them).
                return [_ns(job_id=jid, settings=dataclasses.replace(s, parameters=None, run_as=None))
                        for jid, s in ws.jobs.items()]

            def get(self_inner, job_id):
                return _ns(job_id=job_id, settings=ws.jobs[job_id])

            def create(self_inner, **kw):
                jid = ws.next_job
                ws.next_job += 1
                ws.jobs[jid] = jobs.JobSettings(**kw)
                ws.log.append(("create_job", jid))
                return _ns(job_id=jid)

            def reset(self_inner, job_id, new_settings):
                ws.jobs[job_id] = new_settings
                ws.log.append(("reset_job", job_id))

            def delete(self_inner, job_id):
                ws.jobs.pop(job_id, None)
                ws.log.append(("delete_job", job_id))

            def cancel_all_runs(self_inner, job_id=None):
                ws.log.append(("cancel_runs", job_id))

            def list_runs(self_inner, job_id=None, active_only=None):
                if active_only:
                    return iter([_ns(run_id=1)] if job_id in ws.active else [])
                return iter([_ns(run_id=int(r)) for r in ws.runs.get(job_id, [])])

            def run_now(self_inner, job_id, job_parameters=None):
                params = job_parameters or {}
                applies = ws.tables.setdefault("main.ug_migration.ug_migration_applies", [])
                if params.get("mode") in ("rollback_dry_run", "rollback"):
                    # Like the job (run_apply.py): a run that already counts as rolled back is refused, dry run too.
                    import ug_migration_store as store_mod
                    target = params["rollback_of"]
                    if any(r["mode"] == "rollback" and r.get("rollback_of") == target
                           and store_mod.rollback_done(r["status"], r.get("summary")) for r in applies):
                        ws.log.append(("rollback_refused", target, "already rolled back"))
                        return FakeRun(ws.next_run, behaviour="FAILED", ws=ws)
                if params.get("mode") == "rollback_dry_run":
                    apply_id = params["rollback_of"]
                    script = ws.dry_script.get(apply_id, [("SUCCEEDED", {"would_delete": 1})])
                    status, summary = script.pop(0) if len(script) > 1 else script[0]
                    ws.log.append(("rollback_dry_run", apply_id, status))
                    ws.clock += 1
                    applies.append({"apply_id": params["apply_id"], "mode": "rollback_dry_run", "operation": "apply",
                                    "rollback_of": apply_id, "requested_by": params.get("requested_by", ""),
                                    "status": "RUNNING" if status == "TIMEOUT" else status,
                                    "summary": json.dumps(summary), "started_at": ws._now()})
                    return FakeRun(ws.next_run, behaviour=status if status in ("FAILED", "TIMEOUT") else "SUCCEEDED", ws=ws)
                if params.get("mode") == "rollback":
                    # The real job's gate (notebook/run_apply.py): it refuses a rollback that doesn't cite a finished
                    # rollback dry run of the same execute run by the same requester, used once. The run fails and
                    # writes no row, like the job.
                    apply_id = params["rollback_of"]
                    dry = next((r for r in applies if r["apply_id"] == params.get("dry_run_id")), None)
                    used = next((r["apply_id"] for r in applies if r.get("dry_run_id") and params.get("dry_run_id")
                                 and r["dry_run_id"] == params["dry_run_id"] and r["mode"] == "rollback"), None)
                    refusal = apply_mod.rollback_gate_error(dry, apply_id, params.get("requested_by", ""), used_by=used)
                    if refusal:
                        ws.log.append(("rollback_refused", apply_id, refusal))
                        return FakeRun(ws.next_run, behaviour="FAILED", ws=ws)
                    script = ws.rollback_script.get(apply_id, ["SUCCEEDED"])
                    behaviour = script.pop(0) if len(script) > 1 else script[0]
                    ws.log.append(("rollback", apply_id, behaviour))
                    row = dict(row_id=params["apply_id"], dry_run_id=params["dry_run_id"],
                               requested_by=params.get("requested_by", ""))
                    if behaviour == "TIMEOUT":
                        ws._rollback_row(apply_id, "RUNNING", **row)
                    elif behaviour == "FAILED":
                        ws._rollback_row(apply_id, "FAILED", **row)
                    else:
                        ws._rollback_row(apply_id, behaviour, **row)
                    return FakeRun(ws.next_run, behaviour=behaviour, ws=ws)
                ws.next_run += 1
                ws.log.append(("run_now", job_id, dict(params)))
                return FakeRun(ws.next_run)

        class Apps:
            def list(self_inner, page_size=None):
                return [_without_env_values(a) for a in ws.apps.values()]  # names only, like the real API

            def get(self_inner, name):
                if name in ws.pending_delete:
                    ws.pending_delete[name] -= 1
                    if ws.pending_delete[name] < 0:
                        ws.pending_delete.pop(name)
                        ws.apps.pop(name, None)
                    else:
                        ws.apps[name].compute_status = apps.ComputeStatus(state=apps.ComputeState.DELETING)
                if name not in ws.apps:
                    raise sdk_errors.NotFound(f"app {name} does not exist")
                return _without_env_values(ws.apps[name])

            def create_and_wait(self_inner, app, **kw):
                ws.log.append(("create_app", app.name))
                if getattr(ws, "create_fail", None):  # like the live failure: the app is left in ERROR, with no SP
                    app.compute_status = apps.ComputeStatus(state=apps.ComputeState.ERROR, message=ws.create_fail)
                    ws.apps[app.name] = app
                    raise sdk_errors.OperationFailed(f"failed to reach ACTIVE, got ComputeState.ERROR: {ws.create_fail}")
                app.compute_status = apps.ComputeStatus(state=apps.ComputeState.ACTIVE)
                app.url = f"https://{app.name}.example.app"
                ws.apps[app.name] = app
                return app

            def create_update_and_wait(self_inner, app_name, update_mask, app=None, timeout=None):
                # Like the real partial update: only the masked fields change.
                if getattr(ws, "update_error", None):
                    raise ws.update_error
                ws.log.append(("update_app", app_name))
                ws.update_masks = getattr(ws, "update_masks", []) + [update_mask]
                cur = ws.apps[app_name]
                for f in update_mask.split(","):
                    setattr(cur, f, getattr(app, f))
                return cur

            def update(self_inner, name, app):
                if app.compute_size is not None:  # like the real full-replace API (seen live)
                    raise sdk_errors.InvalidParameterValue("Compute size updates are not supported in this update API.")
                ws.log.append(("update_app", name))
                app.compute_status = ws.apps[name].compute_status
                app.url = ws.apps[name].url
                app.active_deployment = ws.apps[name].active_deployment
                ws.apps[name] = app
                return app

            def stop_and_wait(self_inner, name, timeout=None):
                ws.log.append(("stop_app", name))
                state = ws.apps[name].compute_status.state
                if state != apps.ComputeState.ACTIVE:  # like the API (found by the live uninstall test)
                    raise sdk_errors.BadRequest(f"Cannot stop app {name} as its compute is in {state.value} state. "
                                                "App compute needs to be ACTIVE to stop.")
                ws.apps[name].compute_status = apps.ComputeStatus(state=apps.ComputeState.STOPPED)
                return ws.apps[name]

            def start_and_wait(self_inner, name, timeout=None):
                ws.apps[name].compute_status = apps.ComputeStatus(state=apps.ComputeState.ACTIVE)
                return ws.apps[name]

            def deploy_and_wait(self_inner, name, deployment):
                ws.log.append(("deploy_app", name))
                ws.apps[name].active_deployment = deployment
                return _ns(status=_ns(state=_state("SUCCEEDED")))

            def delete(self_inner, name):
                ws.log.append(("delete_app", name))
                if ws.deleting_polls:
                    ws.pending_delete[name] = ws.deleting_polls
                else:
                    ws.apps.pop(name, None)

        def rule_set(method, path, query=None):
            if path == "/api/2.0/apps":  # the REST list, as the widget cell reads it (the runtime's SDK may be too old)
                names = sorted(ws.apps)
                start = int((query or {}).get("page_token") or 0)
                size = 1  # one app per page, so paging is exercised
                page = [{"name": n, "description": ws.apps[n].description} for n in names[start:start + size]]
                return {"apps": page, **({"next_page_token": str(start + size)} if start + size < len(names) else {})}
            if ws.sp_rules is None:
                raise sdk_errors.PermissionDenied("no access")
            assert path == "/api/2.0/preview/accounts/access-control/rule-sets" and "acct-1" in query["name"]
            return {"grant_rules": ws.sp_rules}

        class Secrets:
            def list_secrets(self_inner, scope):
                if scope not in ws.secret_scopes:
                    raise sdk_errors.ResourceDoesNotExist(f"Scope {scope} does not exist!")
                return [_ns(key=k) for k in sorted(ws.secret_scopes[scope])]

            def get_acl(self_inner, scope, principal):
                perm = ws.secret_acls.get((scope, principal))
                if perm is None:
                    raise sdk_errors.ResourceDoesNotExist(f"Failed to get secret acl for principal {principal}")
                return _ns(principal=principal, permission=_state(perm))

        class ServicePrincipals:
            def list(self_inner, filter=None, attributes=None):
                name = re.match(r'displayName eq "(.*)"', filter or "")[1]
                return [_ns(display_name=n, application_id=a) for n, a in ws.sps if n.lower() == name.lower()]

        return _ns(current_user=Current(), catalogs=Catalogs(), schemas=Schemas(), warehouses=Warehouses(),
                   grants=Grants(), statement_execution=Statements(), workspace=Workspace(), lakeview=Lakeview(),
                   jobs=Jobs(), apps=Apps(), secrets=Secrets(), service_principals=ServicePrincipals(),
                   config=_ns(host="https://ws.example.com"),
                   get_workspace_id=lambda: 123, api_client=_ns(do=rule_set))


def _without_env_values(app):
    """Like the real Apps API (seen live, 2026-11-11): the deployment's environment variables come back with names only."""
    d = app.active_deployment
    if not d or not d.env_vars:
        return app
    shown = dataclasses.replace(app, active_deployment=dataclasses.replace(
        d, env_vars=[apps.EnvVar(name=e.name) for e in d.env_vars]))
    shown.compute_status, shown.url = app.compute_status, app.url
    return shown


def app_obj(name, desc=DESC, env=None):
    a = apps.App(name=name, description=desc, user_api_scopes=["sql"])
    a.compute_status = apps.ComputeStatus(state=apps.ComputeState.ACTIVE)
    a.url = f"https://{name}.example.app"
    if env is not None:
        a.active_deployment = apps.AppDeployment(env_vars=[apps.EnvVar(name=k, value=v) for k, v in env.items()])
    return a


def seed_install(ws, app=APP, folder=FOLDER, results="main.ug_migration", version="0.9.0", pending=(), logs=(),
                 tables=True, schema_comment=None, operators=(ME,)):
    """A complete install made by the installer: app, jobs, schema, tables, marker, files and apply runs.
    pending: (apply_id, created_count, run_id) for execute runs that still have services in place."""
    ws.apps[app] = app_obj(app, env={"RESULTS_SCHEMA": results, "UGMIG_VERSION": version})
    ids = {}
    for role, title, nb in (("snapshot", "snapshot", "run_account"), ("scan", "workspace scan", "run_scan"),
                            ("apply", "apply", "run_apply")):
        params = [jobs.JobParameterDefinition("snapshot_table", f"{results}.ug_migration"),
                  jobs.JobParameterDefinition("deep_warehouse_id", WH_ID)] if role == "snapshot" else [
            jobs.JobParameterDefinition("results_schema", results)]
        s = jobs.JobSettings(name=f"[{app}] Unity Gateway migration {title}",
                             tags={"tool": "ug-migration-toolkit", "Project": "unity-gateway-migration-toolkit",
                                   "app": app, "role": role},
                             parameters=params,
                             tasks=[jobs.Task(task_key=role, notebook_task=jobs.NotebookTask(
                                 notebook_path=f"{folder}/files/notebook/{nb}"))])
        ids[role] = ws.next_job
        ws.jobs[ws.next_job] = s
        ws.next_job += 1
    ws.schemas[results] = {"owner": ME, "comment": schema_comment if schema_comment is not None
                           else f"Unity Gateway migration app results (app: {app})"}
    marker = {"app": app, "version": version, "results": results, "folder": folder, "installed_by": ME}
    if operators is not None:  # a 0.11 marker records them; operators=None is an install from before 0.11.0
        marker["operators"] = list(operators)
    ws.files[f"{folder}/{'ug_migration_toolkit.marker'}"] = json.dumps(marker).encode()
    ws.files[f"{folder}/files/notebook/run_apply"] = b"# x"
    ws.files[f"{folder}/output/account/snapshot.json"] = b"{}"
    if tables:
        for t in RESULT_TABLES:
            ws.tables[f"{results}.ug_migration_{t}"] = []
    apply_job = ids["apply"]
    for n, (aid, created, run) in enumerate(pending):
        ws.tables.setdefault(f"{results}.ug_migration_applies", []).append(
            {"apply_id": aid, "mode": "execute", "rollback_of": None, "status": "SUCCEEDED", "job_run_id": run,
             "started_at": f"2026-10-30T10:0{n}:00"})
        ws.runs.setdefault(apply_job, []).append(run)
        for k in range(created):
            ws.tables.setdefault(f"{results}.ug_migration_apply_items", []).append(
                {"apply_id": aid, "seq": k, "payload": json.dumps({"action": "created", "id": f"{aid}-{k}"})})
    for aid in logs:
        ws.files[f"{folder}/apply_logs/{aid}.jsonl"] = b"{}"
    if logs:
        ws.files[f"{folder}/apply_logs/ug_migration_toolkit.marker"] = b"Unity Gateway migration toolkit logs\n"
    return ids


def seed_jobs_only(ws, name, tags, path="/Workspace/Users/x/.bundle/u/dev/files/notebook/run_apply"):
    jid = ws.next_job
    ws.jobs[jid] = jobs.JobSettings(name=name, tags=tags, tasks=[jobs.Task(task_key="t", notebook_task=jobs.NotebookTask(
        notebook_path=path))])
    ws.next_job += 1
    return jid


def _notebook_text(mode="install"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:  # a stand-in for the real payload
        z.writestr("notebook/run_account.py", "# Databricks notebook source\nprint('account')\n")
        z.writestr("notebook/run_scan.py", "# Databricks notebook source\nprint('scan')\n")
        z.writestr("notebook/run_apply.py", "# Databricks notebook source\nprint('apply')\n")
        z.writestr("USER_GUIDE.md", "guide\n")
        z.writestr("app/backend/main.py", "app = None\n")
    payload = base64.b64encode(buf.getvalue()).decode()
    return make_installer.render(TEXT, mode, "0.9.0", payload)


class Outcome:
    def __init__(self, status, out, ws, labels, params):
        self.status, self.out, self.ws, self.labels, self.params = status, out, ws, labels, params

    @property
    def text(self):
        return "\n".join(self.out)

    @property
    def raised(self):
        return self.status.startswith("raised")


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)


def run_notebook(monkeypatch, ws, widgets=None):
    """Runs the notebook cell by cell. install() gets the old test inputs; uninstall still uses widgets."""
    monkeypatch.setattr(sdk_pkg, "WorkspaceClient", lambda *a, **k: ws.make())
    vals = dict(widgets or {})
    interactive = vals.pop("__interactive__", False)  # default: a job run (the context has a jobId), so no preview
    preview = vals.pop("__preview__", None)
    legacy_job = vals.pop("__legacy_job__", False)
    mode = vals.pop("__mode__", "install")
    text = _notebook_text(mode)
    cells = text.split("\n# COMMAND ----------\n")
    out = []
    labels = {}

    class Widgets:
        def dropdown(self, name, default, choices=None, label=""):
            labels[name] = label
            vals.setdefault(name, default)

        def text(self, name, default, label=""):
            labels[name] = label
            vals.setdefault(name, default)

        def get(self, name):
            return vals[name]  # KeyError for a widget that isn't on the panel, like the runtime's error

        def remove(self, name):
            vals.pop(name, None)

    def exit_(value):
        raise NBExit(value)

    ns = {
        "dbutils": _ns(widgets=Widgets(), notebook=_ns(exit=exit_, entry_point=_ns(getDbutils=lambda: _ns(notebook=lambda: _ns(
            getContext=lambda: _ns(safeToJson=lambda: json.dumps({"attributes": {} if interactive else {"jobId": "1"}}))))))),
        "displayHTML": lambda html: out.append(re.sub(r"<[^>]+>", " ", html)),
        "spark": _ns(sql=ws.sql),
        "print": lambda *a, **k: out.append(" ".join(str(x) for x in a)),
    }
    status = "completed"
    try:
        for i, cell in enumerate(cells):
            if "# MAGIC %restart_python" in cell:
                ns = {k: v for k, v in ns.items() if k in ("dbutils", "spark", "displayHTML", "print")}
            if mode == "install" and "# Settings:" in cell:
                exec(compile(cell, "settings-cell", "exec"), ns)
                if not legacy_job:
                    kwargs = {
                        "catalog": vals.get("01_catalog") or None,
                        "warehouse": vals.get("02_warehouse") or None,
                        "target_schema": vals.get("03_target") or None,
                        "app_name": vals.get("04_app_name") or None,
                        "operators": vals.get("05_operators") or None,
                        "run_as": vals.get("06_run_as") or None,
                        "create_target": vals.get("07_create_target") or None,
                        "results_schema": vals.get("08_results_schema") or None,
                        "install_folder": vals.get("09_install_folder") or None,
                        "secret_schemas": vals.get("10_secret_schemas") or None,
                        "allow_secret_read": vals.get("11_allow_secret_read") or None,
                        "deadline": vals.get("12_deadline") or None,
                        "central_workspaces": vals.get("13_central_workspaces") or None,
                        "central_secret": vals.get("14_central_secret") or None,
                        "adopt_app": vals.get("15_adopt_app") == "yes",
                        "allow_downgrade": vals.get("16_allow_downgrade") == "yes",
                        "second_install": vals.get("17_second_install") == "yes",
                    }
                    kwargs["preview"] = preview if preview is not None else interactive
                    ns["install"](**kwargs)
                continue
            exec(compile(cell, f"cell{i}", "exec"), ns)
    except NBExit as e:
        status = "exit: " + str(e.args[0])
    except Exception as e:  # noqa: BLE001 (the notebook's own failures are the result under test)
        status = f"raised {type(e).__name__}: {e}"
    return Outcome(status, out, ws, labels, ns.get("PARAMS", {}))


# The widget names, by the short names the tests use (the panel numbers them so it shows them in order).
INSTALL_NAMES = {"results_catalog": "01_catalog", "warehouse": "02_warehouse", "target": "03_target",
                 "app_name": "04_app_name", "operators": "05_operators", "run_as": "06_run_as",
                 "create_target": "07_create_target", "results_schema": "08_results_schema",
                 "install_folder": "09_install_folder", "secret_schemas": "10_secret_schemas",
                 "allow_secret_read": "11_allow_secret_read", "deadline": "12_deadline",
                 "central_workspaces": "13_central_workspaces", "central_secret": "14_central_secret",
                 "adopt_app": "15_adopt_app", "allow_downgrade": "16_allow_downgrade", "second_install": "17_second_install"}
UNINSTALL_NAMES = {"action": "01_action", "app_name": "02_app_name", "rollback_services": "03_rollback_services",
                   "drop_data": "04_drop_data", "remove_logs": "05_remove_logs", "results_schema": "06_results_schema",
                   "adopt_app": "07_adopt_app"}


def install_widgets(**kw):
    """Install widgets by short name."""
    vals = {"results_catalog": "main", "warehouse": WH_LABEL, **kw}
    return {"__mode__": "install", **{INSTALL_NAMES[k]: v for k, v in vals.items()}}


def uninstall_widgets(action="uninstall: remove", **kw):
    kw.pop("results_catalog", None)  # the uninstall notebook reads the catalog from the install
    kw.pop("warehouse", None)
    return {"__mode__": "uninstall", UNINSTALL_NAMES["action"]: action.split(": ")[-1],
            **{UNINSTALL_NAMES[k]: v for k, v in kw.items()}}


def snapshot_of(ws):
    return {"apps": sorted(ws.apps), "jobs": sorted(j.name for j in ws.jobs.values()), "schemas": sorted(ws.schemas),
            "tables": sorted(ws.tables), "files": sorted(ws.files)}


@pytest.mark.parametrize("mode", ["install", "uninstall"])
def test_settings_are_the_first_code_cell_and_the_prompt_follows(mode):
    cells = _notebook_text(mode).split("\n# COMMAND ----------\n")
    assert cells[0].startswith("# Databricks notebook source")
    assert "__" not in cells[0].replace("__init__", "")  # every placeholder filled in
    assert ("Installs the toolkit in this workspace" if mode == "install" else "Removes a toolkit install") in cells[0]
    assert any(f'MODE = "{mode}"' in cell for cell in cells)
    if mode == "install":
        assert any("def install(" in cell for cell in cells) and any("# Settings:" in cell for cell in cells)
    else:
        assert any("dbutils.widgets" in cell for cell in cells) and any(cell.strip().endswith("it changes nothing") for cell in cells[1:5])
    assert any("# MAGIC %pip" in cell for cell in cells[1:5])


def _labels(monkeypatch, widgets):
    return run_notebook(monkeypatch, FakeWS(), widgets).labels


def test_the_install_notebook_creates_no_widgets(monkeypatch):
    assert _labels(monkeypatch, install_widgets()) == {}


def test_widgets_from_an_earlier_build_are_removed_without_new_ones(monkeypatch):
    vals = {"__mode__": "install", "__interactive__": True, "01_catalog": "main", "02_warehouse": WH_LABEL,
            "04_setup": "custom", "05_app_name": "", "13_deadline": "", "results_catalog": "main", "action": "install"}
    res = run_notebook(monkeypatch, FakeWS(), vals)
    assert not res.raised, res.status
    assert not res.labels


def test_a_confirmed_new_notebook_installs_with_the_defaults(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "__interactive__": True, "__preview__": False})
    assert not res.raised, res.status
    assert APP in ws.apps and "main.ug_migration" in ws.schemas and "main.ug_migrated" in ws.schemas


def test_without_a_usable_default_catalog_the_first_run_asks_for_one(monkeypatch):
    ws = FakeWS()
    ws.current_catalog = "hive_metastore"  # not usable, and two catalogs to choose from
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "__interactive__": True})
    assert res.raised and "choose catalog" in res.status
    assert not res.labels and snapshot_of(ws) == snapshot_of(FakeWS())


def test_an_update_keeps_catalog_and_warehouse_unless_you_pick_others(monkeypatch):
    ws = FakeWS()
    ws.warehouses["ffff0000"] = {"name": "aaa-first", "state": "RUNNING"}  # sorts first: a new install would pick it
    ids = seed_install(ws)
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "__interactive__": True, "__preview__": False})
    assert not res.raised, res.status
    assert not res.labels
    assert "using the results schema of the existing install: main.ug_migration" in res.text
    assert ws.apps[APP].resources[0].sql_warehouse.id == WH_ID  # not the one a new install would have picked


def test_uninstall_notebook_widgets(monkeypatch):
    lab = _labels(monkeypatch, uninstall_widgets("uninstall: preview"))
    assert list(lab) == ["01_action", "02_app_name", "03_rollback_services", "04_drop_data", "05_remove_logs",
                         "06_results_schema", "07_adopt_app"]
    assert "preview changes nothing" in lab["01_action"]


def test_fresh_install_creates_everything_and_says_what_next(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised, res.status
    assert APP in ws.apps and ws.apps[APP].url == f"https://{APP}.example.app"
    assert {j.name for j in ws.jobs.values()} == {f"[{APP}] Unity Gateway migration {t}" for t in
                                                  ("snapshot", "workspace scan", "apply")}
    assert f"{FOLDER}/ug_migration_toolkit.marker" in ws.files
    assert "main.ug_migration" in ws.schemas
    assert any(e[0] == "run_now" and e[2].get("requested_by") == ME for e in ws.log)  # the first snapshot, not waited for
    text = res.text
    assert "Compute > Apps > ug-migration-toolkit" in text
    assert "First steps" in text and "Start scan" in text
    assert "paused" in text and "unpause" in text
    assert "set secret_schemas to the catalog.schema" in text  # how to turn on secret mapping
    # The schema for new model services is created in the catalog picked, and named everywhere it matters.
    assert ws.schemas["main.ug_migrated"]["comment"] == f"Unity Gateway model services created by the migration toolkit (app: {APP})"
    assert "ai_gateway.migrated" not in ws.schemas
    assert "[OK  ] Schema for new model services: created main.ug_migrated" in text
    assert "New model services go to main.ug_migrated (created by this install)" in text
    assert "ends up in your callers' code" in text
    env = {e.name: e.value for e in ws.apps[APP].active_deployment.env_vars}
    assert env["UGMIG_DEFAULT_TARGET"] == "main.ug_migrated"
    marker = json.loads(ws.files[f"{FOLDER}/ug_migration_toolkit.marker"])
    assert marker["target"] == "main.ug_migrated" and marker["create_target"] is True


def test_install_refuses_without_a_catalog_and_changes_nothing(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "01_catalog": "<choose a catalog>", "02_warehouse": WH_LABEL})
    assert res.raised and "choose catalog" in res.status
    assert snapshot_of(ws) == snapshot_of(FakeWS()) and not ws.apps


def test_a_running_warehouse_is_preselected_and_none_means_choose(monkeypatch):
    ws = FakeWS()
    ws.warehouses = {"ffff0000": {"name": "aaa-stopped", "state": "STOPPED"}, WH_ID: {"name": "serverless", "state": "RUNNING"}}
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "01_catalog": "main"})
    assert not res.raised, res.status
    assert ws.apps[APP].resources[0].sql_warehouse.id == WH_ID  # the running one, though another sorts first by name
    ws2 = FakeWS()
    ws2.warehouses = {}
    res2 = run_notebook(monkeypatch, ws2, {"__mode__": "install", "01_catalog": "main"})
    assert res2.raised and "choose warehouse" in res2.status and not ws2.apps


def test_rerun_keeps_job_ids(monkeypatch):
    ws = FakeWS()
    assert not run_notebook(monkeypatch, ws, install_widgets()).raised
    ids = sorted(ws.jobs)
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised and sorted(ws.jobs) == ids
    assert any(e[0] == "update_app" for e in ws.log)


def test_stopped_warehouse_is_started_before_the_checks(monkeypatch):
    ws = FakeWS()
    ws.warehouses[WH_ID]["state"] = "STOPPED"
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised, res.status
    assert ("start_warehouse", WH_ID) in ws.log
    assert "starting SQL warehouse" in res.text


def test_warehouse_that_wont_start_reports_its_state(monkeypatch):
    ws = FakeWS()
    ws.warehouses[WH_ID]["state"] = "STOPPED"
    ws.start_fails = True
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and "is STOPPED, not RUNNING" in res.status
    assert not ws.apps


def test_each_system_table_is_probed_and_a_missing_grant_is_named(monkeypatch):
    ws = FakeWS()
    ws.denied = {"system.serving.endpoint_usage", "system.access.workspaces_latest"}
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised
    probes = [e[1] for e in ws.log if e[0] == "sql_warehouse" and e[1].startswith("SELECT 1 FROM system.")]
    assert len(probes) == 4  # all four tables the snapshot and scans read
    assert "system.serving.endpoint_usage" in res.status and "system.access.workspaces_latest" in res.status
    assert "GRANT USE SCHEMA, SELECT ON SCHEMA system.serving" in res.status
    assert "GRANT USE SCHEMA, SELECT ON SCHEMA system.access" in res.status
    assert not ws.apps


def test_missing_create_schema_privilege_gives_the_exact_fix(monkeypatch):
    ws = FakeWS()
    ws.no_create = {"main"}
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised
    assert (f"Ask the owner of catalog main (admins) to run: GRANT USE CATALOG, CREATE SCHEMA ON CATALOG `main` "
            f"TO `{ME}`") in res.status
    assert "main.ug_migration" not in ws.schemas and not ws.apps


def test_folder_with_foreign_files_and_no_marker_is_refused(monkeypatch):
    ws = FakeWS()
    ws.files[f"{FOLDER}/my_notes.txt"] = b"mine"
    ws.dirs.add(FOLDER)
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and "won't touch them" in res.status
    assert ws.files[f"{FOLDER}/my_notes.txt"] == b"mine" and not ws.apps


def test_home_folder_itself_is_never_the_install_folder(monkeypatch):
    ws = FakeWS()
    home = f"/Workspace/Users/{ME}"
    ws.files[f"{home}/files/my_notes.txt"] = b"mine"
    res = run_notebook(monkeypatch, ws, install_widgets(install_folder=home))
    assert res.raised and "subfolder of /Workspace/Users/<you>/" in res.status
    assert ws.files[f"{home}/files/my_notes.txt"] == b"mine"


def test_explicit_catalog_that_conflicts_with_existing_results_stops(monkeypatch):
    ws = FakeWS()
    ws.catalogs["other"] = "admins"
    seed_install(ws)
    res = run_notebook(monkeypatch, ws, install_widgets(results_catalog="other"))
    assert res.raised and "already keeps its results in main.ug_migration" in res.status
    assert "other.ug_migration" not in ws.schemas


def test_blank_schema_adopts_the_existing_results(monkeypatch):
    ws = FakeWS()
    seed_install(ws)
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised, res.status
    assert "using the results schema of the existing install: main.ug_migration" in res.text
    assert "main.ug_migration" in ws.schemas


def test_bundle_jobs_without_an_app_tag_are_mentioned_not_named(monkeypatch):
    ws = FakeWS()
    seed_jobs_only(ws, "[dev admin] Unity Gateway migration apply",
                   {"tool": "ug-migration-toolkit", "Project": "unity-gateway-migration-toolkit"})
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised, res.status
    assert "Note: 1 toolkit job(s) deployed by the bundle have no app name" in res.text  # mentioned...
    assert "app dev admin" not in res.text and "'dev admin'" not in res.text  # ...never suggested as an app name
    assert APP in ws.apps and ws.apps[APP].description.startswith("Unity Gateway Migration Toolkit")
    # Uninstall of an unknown name lists only valid app names.
    res2 = run_notebook(monkeypatch, ws, uninstall_widgets(app_name="nope"))
    assert res2.raised and "no install named nope; found: ug-migration-toolkit. Also 1 toolkit job(s)" in res2.status
    assert "app dev admin" not in res2.status  # the bundle job is mentioned, never suggested as an app name


def test_bundle_deployed_app_needs_adopt(monkeypatch):
    ws = FakeWS()
    seed_install(ws, app="ug-migration-bundle", folder=f"/Workspace/Users/{ME}/ug-migration-bundle-toolkit")
    res = run_notebook(monkeypatch, ws, install_widgets(app_name="ug-migration-bundle"))
    assert res.raised and "deployed by the bundle" in res.status and "adopt_app" in res.status
    res2 = run_notebook(monkeypatch, ws, install_widgets(app_name="ug-migration-bundle", adopt_app="yes"))
    assert not res2.raised, res2.status


def test_a_running_job_blocks_install_and_names_it(monkeypatch):
    ws = FakeWS()
    ids = seed_install(ws)
    ws.active.add(ids["snapshot"])
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and f"the job '[{APP}] Unity Gateway migration snapshot' has a run in progress" in res.status
    assert ws.log.count(("upload", f"{FOLDER}/files/notebook/run_account.py")) == 0


def test_uninstall_preview_changes_nothing(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    before = snapshot_of(ws)
    res = run_notebook(monkeypatch, ws, uninstall_widgets(action="uninstall: preview"))
    assert not res.raised and "uninstall preview: nothing changed" in res.status
    assert snapshot_of(ws) == before and ws.log.count(("rollback", A1, "SUCCEEDED")) == 0
    assert "Uninstall removes" in res.text and "Nothing was changed" in res.text


def test_uninstall_rolls_back_newest_first_and_removes_only_toolkit_paths(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1), (A2, 1, RUN2)], logs=[A1, A2])
    ws.files[f"{FOLDER}/my_notes.txt"] = b"not the toolkit's"
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert not res.raised, res.status
    rolled = [e[1] for e in ws.log if e[0] == "rollback"]
    assert rolled == [A2, A1]  # newest first
    stop = ws.log.index(("stop_app", APP))
    assert stop < ws.log.index(("rollback", A2, "SUCCEEDED"))  # the app stops before anything is rolled back
    assert ws.apps == {} and ws.jobs == {}
    assert f"{FOLDER}/ug_migration_toolkit.marker" not in ws.files
    assert f"{FOLDER}/my_notes.txt" in ws.files  # a file the toolkit doesn't own stays
    assert not any(k.startswith(f"{FOLDER}/files") for k in ws.files)
    assert "main.ug_migration" in ws.schemas and "main.ug_migration.ug_migration_applies" in ws.tables  # no drop asked


def test_needs_attention_is_retried_not_fatal(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1), (A2, 1, RUN2)], logs=[A1, A2])
    ws.rollback_script[A2] = ["NEEDS_ATTENTION", "SUCCEEDED"]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert not res.raised, res.status
    assert [e[1] for e in ws.log if e[0] == "rollback"] == [A2, A1, A2]
    assert "pass 1 made progress" in res.text
    assert ws.apps == {}


def test_rollback_that_makes_no_progress_stops_with_the_run_ids(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.rollback_script[A1] = ["FAILED"]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert res.raised and "didn't finish (the last pass made no progress)" in res.status
    assert A1 in res.status and "rollback --log" in res.status
    assert ws.jobs and f"{FOLDER}/ug_migration_toolkit.marker" in ws.files  # nothing else was removed
    assert ws.apps[APP].compute_status.state == apps.ComputeState.STOPPED  # the app is stopped, as the message says


def _attempts(ws, apply_id):
    """The order the fake's job saw for one execute run: dry run, refusal, or rollback."""
    return [e[0] for e in ws.log if e[0] in ("rollback_dry_run", "rollback_refused", "rollback") and e[1] == apply_id]


def test_uninstall_runs_a_rollback_dry_run_first_and_cites_it(monkeypatch):
    """The job refuses a rollback that doesn't cite a finished rollback dry run (0.10.3): uninstall must run one."""
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert not res.raised, res.status
    assert _attempts(ws, A1) == ["rollback_dry_run", "rollback"]
    applies = ws.tables["main.ug_migration.ug_migration_applies"]
    dry = next(r for r in applies if r["mode"] == "rollback_dry_run")
    rb = next(r for r in applies if r["mode"] == "rollback")
    assert rb["dry_run_id"] == dry["apply_id"] and rb["rollback_of"] == dry["rollback_of"] == A1
    assert rb["requested_by"] == dry["requested_by"] == ME  # the gate compares them
    assert rb["status"] == "SUCCEEDED"


def test_fake_job_refuses_a_rollback_without_a_finished_dry_run():
    """The fake enforces the job's gate, so a regression like 0.10.3's first cut (a rollback with no dry_run_id) fails
    in these tests instead of passing against a fake that accepts anything."""
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    jobs_api = ws.make().jobs
    old = {"mode": "rollback", "rollback_of": A1, "results_schema": "main.ug_migration", "requested_by": ME}
    with pytest.raises(sdk_errors.OperationFailed):
        jobs_api.run_now(job_id=1, job_parameters=old).result()
    assert _attempts(ws, A1) == ["rollback_refused"]
    assert not [r for r in ws.tables["main.ug_migration.ug_migration_applies"] if r["mode"] == "rollback"]
    # A dry run of another execute run, or by someone else, is refused too.
    jobs_api.run_now(job_id=1, job_parameters={"mode": "rollback_dry_run", "rollback_of": A2, "apply_id": "d-other",
                                               "requested_by": ME}).result()
    jobs_api.run_now(job_id=1, job_parameters={"mode": "rollback_dry_run", "rollback_of": A1, "apply_id": "d-mine",
                                               "requested_by": "someone@else.com"}).result()
    for dry_id in ("d-other", "d-mine"):
        with pytest.raises(sdk_errors.OperationFailed):
            jobs_api.run_now(job_id=1, job_parameters={**old, "dry_run_id": dry_id, "apply_id": "r"}).result()


def test_uninstall_goes_on_when_the_dry_run_only_keeps_objects(monkeypatch):
    """Kept objects (another run uses them, or they existed before) end a dry run NEEDS_ATTENTION: that is normal."""
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.dry_script[A1] = [("NEEDS_ATTENTION", {"would_delete": 1, "kept": 2, "kept_other_run": 2})]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert not res.raised, res.status
    assert _attempts(ws, A1) == ["rollback_dry_run", "rollback"]


def test_uninstall_stops_when_the_dry_run_had_errors_and_says_why(monkeypatch):
    """An object the dry run couldn't read (error) might be deleted by the rollback without being listed: refused."""
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.dry_script[A1] = [("NEEDS_ATTENTION", {"would_delete": 1, "error": 1})]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert res.raised and "rollback refused after its dry run" in res.status and A1 in res.status
    assert "latest run of Jobs > [ug-migration-toolkit] Unity Gateway migration apply" in res.status
    assert "open the app's Apply page" not in res.status  # the app is stopped by then
    assert _attempts(ws, A1) == ["rollback_dry_run", "rollback_refused"]
    assert ws.jobs and f"{FOLDER}/ug_migration_toolkit.marker" in ws.files  # nothing else was removed


def test_uninstall_stops_when_the_dry_run_failed(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.dry_script[A1] = [("FAILED", {})]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert res.raised and "rollback dry run FAILED" in res.status
    assert _attempts(ws, A1) == ["rollback_dry_run"]  # no rollback after a failed dry run


def test_uninstall_retries_with_a_new_dry_run_each_pass(monkeypatch):
    """Each rollback dry run is good for one rollback, so a second pass runs a new dry run first."""
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1), (A2, 1, RUN2)], logs=[A1, A2])
    ws.rollback_script[A1] = ["NEEDS_ATTENTION", "SUCCEEDED"]  # A2 succeeds in pass 1: progress, so pass 2 runs
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert not res.raised, res.status
    assert _attempts(ws, A1) == ["rollback_dry_run", "rollback", "rollback_dry_run", "rollback"]
    ids = [r["dry_run_id"] for r in ws.tables["main.ug_migration.ug_migration_applies"]
           if r["mode"] == "rollback" and r["rollback_of"] == A1]
    assert len(ids) == 2 and len(set(ids)) == 2


def _summary(**kw):
    base = {"kept": 0, "kept_other_run": 0, "kept_preexisting": 0}
    return {**base, **kw}


@pytest.mark.parametrize("status, summary", [
    ("SUCCEEDED", {}),
    ("SUCCEEDED", _summary(kept=2, kept_other_run=2)),
    ("NEEDS_ATTENTION", _summary(kept=1, kept_other_run=1)),                       # a shared object kept on purpose
    ("NEEDS_ATTENTION", _summary(kept=2, kept_other_run=1, kept_preexisting=1)),
    ("NEEDS_ATTENTION", _summary(kept=2, kept_other_run=1)),                       # one kept for another reason
    ("NEEDS_ATTENTION", _summary(kept=1, kept_other_run=1, error=1)),              # plus an error
    ("NEEDS_ATTENTION", _summary(kept=1, kept_preexisting=1, manual=1)),
    ("NEEDS_ATTENTION", {"error": 1}),                                             # written before kept_other_run existed
    ("NEEDS_ATTENTION", {}),
    ("NEEDS_ATTENTION", None),
    ("NEEDS_ATTENTION", "not json"),
    ("NEEDS_ATTENTION", json.dumps(_summary(kept=1, kept_other_run=1))),           # as stored: a JSON string
    ("RUNNING", _summary()), ("FAILED", _summary()), (None, None),
])
def test_the_installer_and_the_app_agree_on_what_rolled_back_means(status, summary):
    """The uninstall decides what is still pending with its own copy of the rule; it must be the app's rule."""
    import ug_migration_store as store
    assert _helpers()["rollback_done"](status, summary) == store.rollback_done(status, summary)
    assert _helpers()["PROBLEM_ACTIONS"] == apply_mod.PROBLEM_ACTIONS


def test_uninstall_counts_a_run_that_kept_only_a_shared_object_as_rolled_back(monkeypatch):
    """Live finding: a run that reused another run's secret keeps it on purpose, so its rollback ends NEEDS_ATTENTION
    (kept_other_run). The uninstall counted only SUCCEEDED and stopped on it with 'no progress'."""
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.rollback_script[A1] = ["NEEDS_ATTENTION"]
    ws.rollback_summary[A1] = _summary(kept=1, kept_other_run=1)
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert not res.raised, res.status
    assert _attempts(ws, A1) == ["rollback_dry_run", "rollback"]  # one pass was enough
    # A kept object nothing explains still keeps it pending.
    ws2 = FakeWS()
    seed_install(ws2, pending=[(A1, 2, RUN1)], logs=[A1])
    ws2.rollback_script[A1] = ["NEEDS_ATTENTION"]
    res = run_notebook(monkeypatch, ws2, uninstall_widgets(rollback_services="yes"))
    assert res.raised and "didn't finish" in res.status


def test_uninstall_can_be_run_again_after_it_stopped_the_app(monkeypatch):
    """Live finding: the stuck messages say 'run uninstall again', but the app is STOPPED by then and the API refuses to
    stop it again (BadRequest), so the re-run died on the first step."""
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.rollback_script[A1] = ["FAILED", "SUCCEEDED"]
    first = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert first.raised and ws.apps[APP].compute_status.state == apps.ComputeState.STOPPED
    second = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert not second.raised, second.status
    assert APP not in ws.apps  # removed this time
    assert [e for e in ws.log if e[0] == "stop_app"] == [("stop_app", APP)]  # stopped once, not twice


def test_uninstall_waits_for_an_app_that_is_still_starting(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.apps[APP].compute_status = apps.ComputeStatus(state=apps.ComputeState.STARTING)
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert res.raised and "Nothing was changed" in res.status and "STARTING" in res.status
    assert ws.jobs and not [e for e in ws.log if e[0] in ("rollback", "rollback_dry_run", "delete_job")]


def test_timeout_says_still_running_and_how_to_continue(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    ws.rollback_script[A1] = ["TIMEOUT"]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert res.raised
    assert "still running: wait for it to finish (Jobs > [ug-migration-toolkit] Unity Gateway migration apply) and run " \
           "uninstall again" in res.status
    assert "ended RUNNING" not in res.status


def test_up_to_three_passes_then_stop(monkeypatch):
    """Every pass makes progress until the limit: the run stops after MAX_PASSES, not earlier and not later."""
    ws = FakeWS()
    a3, a4 = str(uuid.UUID(int=3)), str(uuid.UUID(int=4))
    seed_install(ws, pending=[(A1, 1, RUN1), (A2, 1, RUN2), (a3, 1, "900003"), (a4, 1, "900004")],
                 logs=[A1, A2, a3, a4])
    ws.rollback_script[A1] = ["NEEDS_ATTENTION"]  # never succeeds
    ws.rollback_script[A2] = ["SUCCEEDED"]
    ws.rollback_script[a3] = ["NEEDS_ATTENTION", "SUCCEEDED"]
    ws.rollback_script[a4] = ["NEEDS_ATTENTION", "NEEDS_ATTENTION", "SUCCEEDED"]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(rollback_services="yes"))
    assert res.raised and "still pending after 3 passes" in res.status
    assert [e[1] for e in ws.log if e[0] == "rollback"].count(A1) == 3
    assert res.text.count("made progress") == 2


def test_drop_with_services_kept_and_logs_removed_is_refused(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    before = snapshot_of(ws)
    res = run_notebook(monkeypatch, ws, uninstall_widgets(drop_data="yes", remove_logs="yes"))
    assert res.raised and "the apply logs are needed" in res.status
    assert snapshot_of(ws) == before and ws.apps


def test_drop_with_services_kept_warns_and_prints_the_rollback_command(monkeypatch):
    ws = FakeWS()
    seed_install(ws, pending=[(A1, 2, RUN1)], logs=[A1])
    res = run_notebook(monkeypatch, ws, uninstall_widgets(drop_data="yes"))
    assert not res.raised, res.status
    assert "WARNING: the results tables are removed while 1 apply run(s) keep their services" in res.text
    assert f'rollback --log "{FOLDER}/apply_logs/{A1}.jsonl"' in res.text
    assert "main.ug_migration.ug_migration_applies" not in ws.tables
    assert f"{FOLDER}/apply_logs/{A1}.jsonl" in ws.files  # the log is kept for the later rollback
    assert ws.apps == {}


def test_drop_is_refused_when_the_results_schema_is_shared(monkeypatch):
    ws = FakeWS()
    seed_install(ws)
    other = seed_jobs_only(ws, f"[other] Unity Gateway migration scan", {
        "tool": "ug-migration-toolkit", "Project": "unity-gateway-migration-toolkit", "app": "other", "role": "scan"},
        path="/Workspace/Users/x/other/files/notebook/run_scan")
    ws.jobs[other].parameters = [jobs.JobParameterDefinition("results_schema", "main.ug_migration")]
    res = run_notebook(monkeypatch, ws, uninstall_widgets(drop_data="yes", app_name=APP))
    assert res.raised and "is shared with the toolkit install of app other" in res.status
    assert APP in ws.apps and "main.ug_migration.ug_migration_applies" in ws.tables


def test_uninstall_of_an_unknown_name_stops_and_lists_the_installs(monkeypatch):
    ws = FakeWS()
    seed_install(ws)
    res = run_notebook(monkeypatch, ws, uninstall_widgets(app_name="does-not-exist"))
    assert res.raised and "no install named does-not-exist; found: ug-migration-toolkit" in res.status
    assert APP in ws.apps and "Done." not in res.text


def test_uninstall_keeps_files_when_the_marker_is_not_this_apps(monkeypatch):
    ws = FakeWS()
    seed_install(ws)
    ws.files[f"{FOLDER}/ug_migration_toolkit.marker"] = json.dumps({"app": "someone-else"}).encode()
    res = run_notebook(monkeypatch, ws, uninstall_widgets())
    assert not res.raised, res.status
    assert "kept the files in " + FOLDER in res.text
    # Nothing in the folder is deleted without this app's marker; the app and jobs still go.
    assert f"{FOLDER}/files/notebook/run_apply" in ws.files and f"{FOLDER}/output/account/snapshot.json" in ws.files
    assert ws.apps == {} and ws.jobs == {}


def test_drop_keeps_a_schema_the_toolkit_did_not_create(monkeypatch):
    ws = FakeWS()
    seed_install(ws, schema_comment="my team's schema")
    res = run_notebook(monkeypatch, ws, uninstall_widgets(drop_data="yes"))
    assert not res.raised, res.status
    assert "kept schema main.ug_migration (the toolkit didn't create it)" in res.text
    assert "main.ug_migration" in ws.schemas and "main.ug_migration.ug_migration_applies" not in ws.tables


def test_reinstall_right_after_uninstall_waits_for_the_app_to_go(monkeypatch):
    ws = FakeWS()
    seed_install(ws)
    ws.deleting_polls = 2
    assert not run_notebook(monkeypatch, ws, uninstall_widgets()).raised
    assert APP not in ws.apps and APP not in ws.pending_delete  # the uninstall waited until the name was free
    ws.deleting_polls = 0
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised, res.status
    assert APP in ws.apps and ws.apps[APP].compute_status.state == apps.ComputeState.ACTIVE


def test_install_leaves_a_schema_comment_it_did_not_make(monkeypatch):
    ws = FakeWS()
    ws.schemas["main.ug_migration"] = {"owner": ME, "comment": "my team's schema"}
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised, res.status
    assert ws.schemas["main.ug_migration"]["comment"] == "my team's schema"


def test_cutover_job_parameters_and_the_deadline_reach_the_jobs_and_app():
    specs = H["job_specs"](APP, FOLDER, "main.ug_migration", WH_ID, ["main.s"], True, "2027-06-01")
    apply_params = {p.name: p.default for p in specs["apply"].parameters}
    assert apply_params["operation"] == "apply" and apply_params["api_type"] == ""
    assert apply_params["prompt"] == "Reply with: ok" and apply_params["services"] == ""
    assert {p.name: p.default for p in specs["snapshot"].parameters}["deadline"] == "2027-06-01"
    assert {p.name: p.default for p in specs["scan"].parameters}["deadline"] == "2027-06-01"
    env = {e.name: e.value for e in H["app_env"]("main.ug_migration", ["a@x.com"], "0.9.0", ["main.s"], False,
                                                 "2027-06-01")}
    assert env["UGMIG_DEADLINE"] == "2027-06-01"
    default_env = {e.name: e.value for e in H["app_env"]("main.ug_migration", ["a@x.com"], "0.9.0", ["main.s"], False)}
    assert default_env["UGMIG_DEADLINE"] == "2027-03-30" == H["DEFAULT_DEADLINE"]
    assert H["valid_deadline"]("2027-03-30") is None
    assert "YYYY-MM-DD" in H["valid_deadline"]("30/03/2027")


def test_legacy_deadline_argument_is_validated_and_passed_on(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets(deadline="next spring"))
    assert res.raised and "deadline must be a date as YYYY-MM-DD" in res.status
    assert not ws.apps  # nothing created for a bad date
    res2 = run_notebook(monkeypatch, ws, install_widgets(deadline="2027-06-01"))
    assert not res2.raised, res2.status
    env = {e.name: e.value for e in ws.apps[APP].active_deployment.env_vars}
    assert env["UGMIG_DEADLINE"] == "2027-06-01"
    snap = [j for j in ws.jobs.values() if j.tags["role"] == "snapshot"][0]
    assert {p.name: p.default for p in snap.parameters}["deadline"] == "2027-06-01"


def test_service_principal_install_needs_operators(monkeypatch):
    ws = FakeWS(me="0b1f7c2e-1234-4abc-9def-0123456789ab")
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and "set operators" in res.status
    res2 = run_notebook(monkeypatch, ws, install_widgets(operators="boss@example.com"))
    assert not res2.raised, res2.status
    env = {e.name: e.value for e in ws.apps[APP].active_deployment.env_vars}
    assert env["OPERATORS"] == "boss@example.com"


def test_install_job_parameters_match_the_contract(monkeypatch):
    ws = FakeWS()
    assert not run_notebook(monkeypatch, ws, install_widgets()).raised
    by_role = {j.tags["role"]: {p.name: p.default for p in j.parameters} for j in ws.jobs.values()}
    assert by_role["apply"]["smoke_test"] == "false" and by_role["apply"]["force"] == "false"
    assert by_role["apply"]["grants"] == "false"
    assert by_role["snapshot"]["deep_wave"] == ""
    assert (by_role["scan"]["target_catalog"], by_role["scan"]["target_schema"]) == ("main", "ug_migrated")



SP_ID = "5e1f7c2e-1234-4abc-9def-0123456789ab"


def test_job_specs_run_as_a_service_principal_or_the_installer():
    mine = H["job_specs"](APP, FOLDER, "main.ug_migration", WH_ID, [], False)
    assert all(spec.run_as is None for spec in mine.values())  # blank: the jobs run as the installing user
    sp = H["job_specs"](APP, FOLDER, "main.ug_migration", WH_ID, [], False, "2027-03-30", SP_ID)
    assert all(spec.run_as == jobs.JobRunAs(service_principal_name=SP_ID) for spec in sp.values())
    assert {p.name: p.default for p in sp["apply"].parameters}["dry_run_id"] == ""
    assert H["valid_run_as"]("") is None and H["valid_run_as"](SP_ID) is None
    assert "application ID" in H["valid_run_as"]("my-sp")


def test_install_with_run_as_sets_the_jobs_and_shares_the_folder(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets(run_as=SP_ID))
    assert not res.raised, res.status
    assert all(j.run_as == jobs.JobRunAs(service_principal_name=SP_ID) for j in ws.jobs.values())
    ((typ, _, acl),) = ws.permission_updates
    assert typ == "directories" and acl[0].service_principal_name == SP_ID
    assert f"Jobs run as service principal {SP_ID}" in res.text
    bad = run_notebook(monkeypatch, FakeWS(), install_widgets(run_as="not-a-uuid"))
    assert bad.raised and "application ID" in bad.status


def test_install_with_run_as_stops_early_without_the_service_principal_user_role(monkeypatch):
    ws = FakeWS()
    ws.sp_rules = [{"principals": [f"users/{ME}"], "role": "roles/servicePrincipal.manager"}]
    res = run_notebook(monkeypatch, ws, install_widgets(run_as=SP_ID))
    assert res.raised and "Service principal: User" in res.status and "Manager isn't enough" in res.status
    assert not ws.jobs and not ws.apps and not ws.files  # nothing was changed
    ok = FakeWS()
    ok.sp_rules = [{"principals": [f"users/{ME}"], "role": "roles/servicePrincipal.user"}]
    res2 = run_notebook(monkeypatch, ok, install_widgets(run_as=SP_ID))
    assert not res2.raised, res2.status


def test_a_failed_app_create_is_explained_and_the_next_install_recreates_it(monkeypatch):
    ws = FakeWS()
    ws.create_fail = "Failed to create app service principal due to error: RESOURCE_EXHAUSTED: too many principals"
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and "couldn't create app" in res.status and "RESOURCE_EXHAUSTED" in res.status
    assert "run the installer again" in res.status and ws.apps[APP].compute_status.state == apps.ComputeState.ERROR
    ws.create_fail = None
    ws.log.clear()
    res2 = run_notebook(monkeypatch, ws, install_widgets())
    assert not res2.raised, res2.status
    names = [e[0] for e in ws.log if e[0] in ("delete_app", "create_app", "update_app")]
    assert names == ["delete_app", "create_app"]
    assert ws.apps[APP].compute_status.state == apps.ComputeState.ACTIVE and "removing it to create it again" in res2.text


def test_install_says_the_first_snapshot_is_account_wide_before_it_starts(monkeypatch):
    res = run_notebook(monkeypatch, FakeWS(), install_widgets())
    assert not res.raised, res.status
    text = res.text
    notice = text.index("every workspace in the account")
    assert notice < text.index("First snapshot started")
    assert f"The jobs will run as {ME}" in text
    assert "account-wide system tables" in _notebook_text().split("\n# COMMAND ----------\n")[0]  # the intro says it too


def test_app_update_errors_surface_and_only_a_missing_api_falls_back(monkeypatch):
    ws = FakeWS()
    seed_install(ws)
    ws.update_error = sdk_errors.PermissionDenied("not allowed to update this app")
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and "PermissionDenied" in res.status and "not allowed" in res.status
    ws.update_error = sdk_errors.NotImplemented("no partial update here")
    res2 = run_notebook(monkeypatch, ws, install_widgets())
    assert not res2.raised, res2.status
    assert "updated app" in res2.text


def test_update_changes_only_the_fields_the_installer_owns():
    ns = H
    assert ns["APP_UPDATE_MASK"] == "description,resources,user_api_scopes"


# ---------------------------------------------------------------------------------------------------------------------
# 0.11.0: install(...) replaces the install widgets, with preview first for people and execute for jobs


def test_install_call_replaces_install_widgets_only():
    install_cells = _notebook_text("install").split("\n# COMMAND ----------\n")
    assert any("def install(" in cell for cell in install_cells)
    assert 'D("01_catalog"' not in install_cells[1] and 'T("03_target"' not in install_cells[1]
    assert any("# Settings:" in cell for cell in install_cells)
    uninstall_cells = _notebook_text("uninstall").split("\n# COMMAND ----------\n")
    assert any('dbutils.widgets.dropdown("01_action"' in cell for cell in uninstall_cells)


def test_install_helpers_live_after_restart_and_visible_cell_is_only_the_call():
    cells = _notebook_text("install").split("\n# COMMAND ----------\n")
    restart = next(i for i, cell in enumerate(cells) if "%restart_python" in cell)
    helper = next(i for i, cell in enumerate(cells) if "def install(" in cell)
    visible = next(i for i, cell in enumerate(cells) if "# Settings:" in cell)
    assert restart < helper < visible
    assert "MODE" in cells[helper] and "_in_job" in cells[helper] and "PARAMS" in cells[helper]
    assert "def install(" not in cells[visible]
    assert "install(" in cells[visible]
    assert all(f"{name}=None" in cells[visible] for name in ("catalog", "warehouse", "target_schema"))
    assert "preview=True" in cells[visible]
    assert "if MODE" not in cells[visible]
    assert "edit install(...) above" not in cells[visible]
    assert "Run all to preview" in cells[visible]


def test_default_catalog_falls_back_to_the_only_usable_catalog(monkeypatch):
    ws = FakeWS()
    ws.current_catalog = "missing-from-metastore"
    ws.catalogs = {"main": "admins"}
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "__interactive__": True, "__preview__": False})
    assert not res.raised, res.status
    assert "main.ug_migration" in ws.schemas and "main.ug_migrated" in ws.schemas
    assert "missing-from-metastore.ug_migration" not in ws.schemas


def test_install_call_records_bool_and_list_settings(monkeypatch):
    widgets = install_widgets(allow_secret_read=True, operators=["ops@example.com", ME], secret_schemas=["main.sec"])
    widgets["__preview__"] = False
    res = run_notebook(monkeypatch, FakeWS(), widgets)
    assert res.params["allow_secret_read"] is True
    assert res.params["operators"] == ["ops@example.com", ME]
    assert res.params["secret_schemas"] == ["main.sec"]
    assert res.params["preview"] is False


def test_warehouse_choice_resolves_name_id_and_unambiguous_default():
    warehouses = [{"id": "abc123", "name": "shared", "state": "RUNNING"}]
    assert H["warehouse_choice"]("shared", "", warehouses) == ("abc123", None)
    assert H["warehouse_choice"]("abc123", "", warehouses) == ("abc123", None)
    assert H["warehouse_choice"]("", "", warehouses) == ("abc123", None)
    assert H["warehouse_choice"]("", "saved-id", warehouses) == ("saved-id", None)


def test_warehouse_choice_rejects_ambiguity():
    warehouses = [{"id": "a", "name": "one", "state": "RUNNING"}, {"id": "b", "name": "two", "state": "RUNNING"}]
    warehouse_id, problem = H["warehouse_choice"]("", "", warehouses)
    assert not warehouse_id and "several running warehouses" in problem
    warehouse_id, problem = H["warehouse_choice"]("missing", "", warehouses)
    assert not warehouse_id and "wasn't found" in problem


def test_interactive_preview_does_not_start_a_warehouse_or_create_schemas(monkeypatch):
    ws = FakeWS()
    ws.warehouses[WH_ID]["state"] = "STOPPED"
    before = snapshot_of(ws)
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "__interactive__": True})
    assert res.status == "exit: install preview: nothing changed", res.status
    assert snapshot_of(ws) == before
    assert "Checklist:" in res.text and "This install would create or update:" in res.text
    assert "preview=False" in res.text and "will be started" in res.text
    assert "(will be created after confirmation)" in res.text
    assert "not created (see the checklist)" not in res.text


def test_preview_with_service_principal_does_not_grant_results_access(monkeypatch):
    ws = FakeWS()
    widgets = install_widgets(run_as=SP_ID, operators=f"{ME},ops@example.com")
    widgets["__interactive__"] = True
    res = run_notebook(monkeypatch, ws, widgets)
    assert res.status == "exit: install preview: nothing changed", res.status
    assert not ws.tables and not any("SELECT ON SCHEMA" in e[1] for e in ws.log if e[0] == "sql")


def test_confirmed_install_executes_and_starts_the_warehouse(monkeypatch):
    ws = FakeWS()
    ws.warehouses[WH_ID]["state"] = "STOPPED"
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "__interactive__": True, "__preview__": False})
    assert not res.raised, res.status
    assert ws.warehouses[WH_ID]["state"] == "RUNNING"
    assert APP in ws.apps and "main.ug_migration" in ws.schemas and "main.ug_migrated" in ws.schemas


def test_preview_and_uninstall_exits_follow_their_output_cells():
    install_cells = _notebook_text("install").split("\n# COMMAND ----------\n")
    output = next(i for i, cell in enumerate(install_cells) if "This install would create or update:" in cell)
    exit_cell = next(i for i, cell in enumerate(install_cells) if 'exit("install preview: nothing changed")' in cell)
    assert exit_cell > output
    assert 'exit("install preview: nothing changed")' not in install_cells[output]
    uninstall_cells = _notebook_text("uninstall").split("\n# COMMAND ----------\n")
    preview = next(i for i, cell in enumerate(uninstall_cells) if "Uninstall removes:" in cell)
    preview_exit = next(i for i, cell in enumerate(uninstall_cells) if 'exit("uninstall preview: nothing changed")' in cell)
    assert preview_exit > preview
    assert "Uninstall removes:" not in uninstall_cells[preview_exit]
    done = next(i for i, cell in enumerate(uninstall_cells) if 'print("Done. Kept:' in cell)
    done_exit = next(i for i, cell in enumerate(uninstall_cells) if 'exit("uninstalled")' in cell)
    assert done_exit > done
    assert "Done. Kept:" not in uninstall_cells[done_exit]
    assert "Toolkit files" in make_installer.PROMPT["install"]
    assert "Edit install" not in make_installer.PROMPT["install"]


def test_no_input_update_ignores_stale_install_widgets(monkeypatch):
    ws = FakeWS()
    ids = seed_install(ws)
    for job in ws.jobs.values():
        job.run_as = jobs.JobRunAs(service_principal_name=SP_ID)
    ws.warehouses["ffff0000"] = {"name": "stale", "state": "RUNNING"}
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "__interactive__": True, "__preview__": False,
                                        "01_catalog": "other", "02_warehouse": "stale (ffff0000)", "06_run_as": "stale"})
    assert not res.raised, res.status
    assert ws.apps[APP].resources[0].sql_warehouse.id == WH_ID
    assert all(j.run_as == jobs.JobRunAs(service_principal_name=SP_ID) for j in ws.jobs.values())
    assert "other.ug_migrated" not in ws.schemas and "other.ug_migration" not in ws.schemas


def test_explicit_hive_metastore_is_rejected_before_any_write(monkeypatch):
    ws = FakeWS()
    ws.catalogs["hive_metastore"] = "admins"
    before = snapshot_of(ws)
    widgets = install_widgets(results_catalog="hive_metastore")
    widgets["__preview__"] = False
    res = run_notebook(monkeypatch, ws, widgets)
    assert res.raised and "hive_metastore isn't supported" in res.status, res.status
    assert snapshot_of(ws) == before


# ---------------------------------------------------------------------------------------------------------------------
# 0.11.0: quick setup, the schema for new model services, one checklist, and updates that keep their settings

def test_pick_keeps_the_install_setting_and_none_clears_it():
    pick = H["pick"]
    assert pick("", "saved", "default") == "saved"
    assert pick("", "", "default") == "default"
    assert pick("typed", "saved", "default") == "typed"
    assert pick(" none ", "saved", "default") == "default" and pick("OFF", "saved", "") == ""


def test_parse_target():
    assert H["parse_target"]("main.ug_migrated") == ("main.ug_migrated", None)
    assert H["parse_target"]("`main`.`ug-x`") == ("main.ug-x", None)
    for bad in ("main", "a.b.c", "main.", "ma in.x"):
        assert "must be catalog.schema" in H["parse_target"](bad)[1], bad


def test_app_name_for_finds_the_one_install_here():
    f = H["app_name_for"]
    assert f("", [], False)[0] == APP
    assert f("", [APP, "other-app"], False)[0] == APP
    assert "several toolkit installs" in f("", [APP, "other-app"], True)[2]  # uninstall never picks one of several
    name, note, problem = f("", ["unity-gateway-migration"], False)
    assert name == "unity-gateway-migration" and "updating it" in note and problem is None
    assert "removing it" in f("", ["unity-gateway-migration"], True)[1]
    _, _, problem = f("", ["a-app", "b-app"], True)
    assert "several toolkit installs (a-app, b-app): set 2. App name" in problem
    assert f("mine", ["a-app", "b-app"], False) == ("mine", None, None)


def test_saved_settings_reads_jobs_and_app_env():
    jobs_of_app = [
        {"role": "scan", "params": {"target_catalog": "ai_gateway", "target_schema": "migrated", "central_workspaces": "1,2",
                                    "central_secret": "s/k", "deadline": "2027-03-30"}, "run_as": SP_ID},
        {"role": "apply", "params": {"secret_schemas": "main.sec", "allow_secret_read_enabled": "true"}, "run_as": SP_ID},
        {"role": "snapshot", "params": {"deep_warehouse_id": WH_ID}, "run_as": SP_ID}]
    got = H["saved_settings"](jobs_of_app, {"OPERATORS": "a@x.com,b@x.com"})
    assert got == {"warehouse": WH_ID, "run_as": SP_ID, "target": "ai_gateway.migrated", "central_workspaces": "1,2",
                   "central_secret": "s/k", "secret_schemas": "main.sec", "allow_secret_read": "yes",
                   "deadline": "2027-03-30", "operators": "a@x.com,b@x.com"}
    assert H["saved_settings"]([], {})["target"] == "" and H["saved_settings"]([], {})["allow_secret_read"] == ""


def _env(ws):
    return {e.name: e.value for e in ws.apps[APP].active_deployment.env_vars}


def test_an_update_with_no_widgets_set_keeps_every_setting(monkeypatch):
    """Import the newer installer and Run all: a fresh notebook has empty widgets, and nothing may change."""
    ws = FakeWS()
    ws.warehouses["ffff0000"] = {"name": "other", "state": "RUNNING"}  # several warehouses: none preselected
    ws.schemas["main.services"] = {"owner": ME, "comment": ""}
    first = run_notebook(monkeypatch, ws, install_widgets(target="main.services", run_as=SP_ID,
                                                          operators="a@x.com,b@x.com", secret_schemas="main.sec",
                                                          allow_secret_read="yes", deadline="2027-06-01"))
    assert not first.raised, first.status
    before = {r: (j.parameters, j.run_as) for r, j in ((j.tags["role"], j) for j in ws.jobs.values())}
    env_before = _env(ws)
    again = run_notebook(monkeypatch, ws, {"__mode__": "install"})  # nothing picked at all
    assert not again.raised, again.status
    assert {r: (j.parameters, j.run_as) for r, j in ((j.tags["role"], j) for j in ws.jobs.values())} == before
    assert _env(ws) == env_before
    assert "kept from the existing install: operators, run-as service principal, schema for new model services, SQL " \
           "warehouse, secret schemas, deadline" in again.text


def test_an_update_from_0_10_keeps_the_old_target_and_doesnt_create_it_elsewhere(monkeypatch):
    ws = FakeWS()
    ids = seed_install(ws)
    scan = ws.jobs[ids["scan"]]
    scan.parameters += [jobs.JobParameterDefinition("target_catalog", "ai_gateway"),
                        jobs.JobParameterDefinition("target_schema", "migrated")]
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "02_warehouse": WH_LABEL})
    assert not res.raised, res.status
    assert {p.name: p.default for p in ws.jobs[ids["scan"]].parameters}["target_catalog"] == "ai_gateway"
    assert _env(ws)["UGMIG_DEFAULT_TARGET"] == "ai_gateway.migrated"
    assert "main.ug_migrated" not in ws.schemas  # the old target stays; nothing new is made in another catalog
    assert "[NOTE] Schema for new model services: catalog ai_gateway doesn't exist" in res.text
    assert "CREATE SCHEMA IF NOT EXISTS `ai_gateway`.`migrated`;" in res.text  # the SQL, at the end


def test_target_schema_that_exists_is_used_as_is(monkeypatch):
    ws = FakeWS()
    ws.schemas["other.mine"] = {"owner": "admins", "comment": "theirs"}
    res = run_notebook(monkeypatch, ws, install_widgets(target="other.mine"))
    assert not res.raised, res.status
    assert ws.schemas["other.mine"]["comment"] == "theirs" and "main.ug_migrated" not in ws.schemas
    assert "[OK  ] Schema for new model services: other.mine exists" in res.text
    assert "(already exists, kept as is)" in res.text


@pytest.mark.parametrize("setup, expect", [
    ({"create_target": "no"}, "and create_target=False."),
    ({"target": "nocat.svc"}, "catalog nocat doesn't exist"),
    ({"no_create": True}, "couldn't create main.ug_migrated"),
])
def test_a_target_schema_that_cant_be_made_never_stops_the_install(monkeypatch, setup, expect):
    ws = FakeWS()
    widgets = dict(setup)
    if widgets.pop("no_create", False):
        ws.no_create.add("main")
        ws.schemas["main.ug_migration"] = {"owner": ME, "comment": f"Unity Gateway migration app results (app: {APP})"}
    res = run_notebook(monkeypatch, ws, install_widgets(**widgets))
    assert not res.raised, res.status
    assert APP in ws.apps
    assert "[NOTE] Schema for new model services" in res.text and expect in res.text
    assert not [k for k in ws.schemas if k.endswith((".ug_migrated", ".svc"))]
    assert "Apply waits until it exists" in res.text or "before you use Apply" in res.text


def test_run_as_service_principal_gets_the_target_grants(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets(run_as=SP_ID))
    assert not res.raised, res.status
    sql = [e[1] for e in ws.log if e[0] == "sql"]
    assert f"GRANT USE CATALOG ON CATALOG `main` TO `{SP_ID}`" in sql
    assert f"GRANT USE SCHEMA, CREATE SERVICE ON SCHEMA `main`.`ug_migrated` TO `{SP_ID}`"[:100] in sql  # log keeps 100
    assert f"granted: GRANT USE SCHEMA, CREATE SERVICE ON SCHEMA `main`.`ug_migrated` TO `{SP_ID}`;" in res.text


def test_run_as_service_principal_lets_you_and_the_operators_read_the_results(monkeypatch):
    """The service principal owns the results tables it creates; owning the catalog doesn't let you read them, and the
    app reads as the signed-in user (seen live: "does not have SELECT on Table ...")."""
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets(run_as=SP_ID, operators="ops@example.com"))
    assert not res.raised, res.status
    for who in (ME, "ops@example.com"):  # you are granted even when you aren't listed as an operator
        assert f"granted: GRANT USE SCHEMA, SELECT ON SCHEMA `main`.`ug_migration` TO `{who}`;" in res.text
        assert f"granted: GRANT USE CATALOG ON CATALOG `main` TO `{who}`;" in res.text
    assert f"SELECT ON SCHEMA `main`.`ug_migration` TO `{SP_ID}`" not in res.text  # the jobs' identity owns the tables
    res = run_notebook(monkeypatch, FakeWS(), install_widgets(run_as=SP_ID, operators=f"{ME}, ops@example.com"))
    assert res.text.count(f"SELECT ON SCHEMA `main`.`ug_migration` TO `{ME}`") == 1  # no duplicate for you


def test_when_the_jobs_run_as_you_the_other_operators_still_get_read_access(monkeypatch):
    """You own the tables then, so you need no grant, but the other operators do (review of 0.10.4)."""
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets(operators=f"{ME}, ops@example.com"))
    assert not res.raised, res.status
    assert "granted: GRANT USE SCHEMA, SELECT ON SCHEMA `main`.`ug_migration` TO `ops@example.com`;" in res.text
    assert f"SELECT ON SCHEMA `main`.`ug_migration` TO `{ME}`" not in res.text
    res = run_notebook(monkeypatch, FakeWS(), install_widgets())
    assert "granted: GRANT USE SCHEMA, SELECT ON SCHEMA" not in res.text  # only you: nothing to grant


def test_results_read_grants_skip_the_jobs_identity_and_bad_names():
    g = H["results_read_grants"]
    assert g("c.s", "", ["a@x.com"]) == []
    assert g("c.s", "SP", ["a@x.com", "A@x.com", "", "sp", "b`c@x.com"]) == [
        "GRANT USE CATALOG ON CATALOG `c` TO `a@x.com`;", "GRANT USE SCHEMA, SELECT ON SCHEMA `c`.`s` TO `a@x.com`;"]


def test_none_clears_a_kept_setting(monkeypatch):
    ws = FakeWS()
    assert not run_notebook(monkeypatch, ws, install_widgets(run_as=SP_ID)).raised
    res = run_notebook(monkeypatch, ws, install_widgets(run_as="none"))
    assert not res.raised, res.status
    assert all(j.run_as is None for j in ws.jobs.values())


def test_checklist_lists_passes_and_fixes_and_nothing_changes(monkeypatch):
    ws = FakeWS()
    ws.denied.add("system.serving.endpoint_usage")
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and "Nothing was changed. Fix the FIX items in the checklist above" in res.status
    text = res.text
    assert "Checklist:" in text and "[OK  ] Databricks Apps" in text and "[OK  ] SQL warehouse" in text
    assert "[FIX ] the SQL warehouse can't read system.serving.endpoint_usage" in text
    assert "[OK  ] Schema for new model services: main.ug_migrated doesn't exist: it will be created" in text
    assert not ws.apps and "main.ug_migrated" not in ws.schemas  # a failed check: nothing made, not even the target
    assert "This install creates or updates" not in text


def test_the_install_lists_what_it_creates_before_it_starts(monkeypatch):
    res = run_notebook(monkeypatch, FakeWS(), install_widgets())
    text = res.text
    i = text.index("This install creates or updates:")
    assert i < text.index("wrote ")  # before the first file is written
    for part in (f"Toolkit files: {FOLDER}", "Results schema (scan results and history): main.ug_migration",
                 "Schema for new model services (Apply creates services here, only when you run it): main.ug_migrated",
                 f"App: {APP}"):
        assert part in text


def test_quick_update_finds_an_install_with_another_name(monkeypatch):
    ws = FakeWS()
    seed_install(ws, app="unity-gateway-migration", folder="/Workspace/Users/admin@example.com/unity-gateway-migration")
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "02_warehouse": WH_LABEL})
    assert not res.raised, res.status
    assert "found the install of app unity-gateway-migration in this workspace: updating it" in res.text
    assert set(ws.apps) == {"unity-gateway-migration"}


def test_uninstall_with_a_blank_name_finds_the_only_install(monkeypatch):
    ws = FakeWS()
    seed_install(ws, app="unity-gateway-migration", folder="/Workspace/Users/admin@example.com/unity-gateway-migration")
    res = run_notebook(monkeypatch, ws, uninstall_widgets("uninstall: preview"))
    assert res.status == "exit: uninstall preview: nothing changed", res.status
    assert "removing it" in res.text and "schemas where Apply created model services" in res.text


def test_built_notebooks_are_both_committed_and_the_uninstaller_has_no_payload(tmp_path):
    path = make_installer.build(str(tmp_path), check_fresh=False)
    un = tmp_path / ("UN" + pathlib.Path(path).name)
    assert un.exists()
    text = un.read_text()
    assert 'MODE = "uninstall"' in text and 'PAYLOAD = ""' in text
    assert un.stat().st_size < 200_000 < pathlib.Path(path).stat().st_size


def test_an_update_from_0_10_asks_for_the_operators_once_then_keeps_them(monkeypatch):
    """Installs before 0.11.0 didn't record the operators, and the Apps API doesn't return them: the update asks once
    (a FIX, nothing changed) instead of silently resetting who can start jobs."""
    ws = FakeWS()
    seed_install(ws, operators=None)
    before = snapshot_of(ws)
    res = run_notebook(monkeypatch, ws, {"__mode__": "install", "02_warehouse": WH_LABEL})
    assert res.raised and "the operators of this install" in res.status and "Enter them in operators" in res.status
    assert snapshot_of(ws) == before
    ok = run_notebook(monkeypatch, ws, install_widgets(operators="boss@example.com,ops@example.com"))
    assert not ok.raised, ok.status
    assert json.loads(ws.files[f"{FOLDER}/ug_migration_toolkit.marker"])["operators"] == ["boss@example.com", "ops@example.com"]
    again = run_notebook(monkeypatch, ws, {"__mode__": "install", "02_warehouse": WH_LABEL})
    assert not again.raised and "kept from the existing install: operators" in again.text
    assert _env(ws)["OPERATORS"] == "boss@example.com,ops@example.com"


def test_a_blank_create_target_keeps_a_saved_no(monkeypatch):
    ws = FakeWS()
    assert not run_notebook(monkeypatch, ws, install_widgets(create_target="no")).raised
    assert "main.ug_migrated" not in ws.schemas
    res = run_notebook(monkeypatch, ws, install_widgets())  # create_target left blank: the saved "no" is kept
    assert not res.raised, res.status
    assert "main.ug_migrated" not in ws.schemas and "create_target=False" in res.text


def test_turning_central_mode_off_also_drops_its_secret(monkeypatch):
    ws = FakeWS()
    assert not run_notebook(monkeypatch, ws, install_widgets(run_as=SP_ID, central_workspaces="111",
                                                             central_secret="s/k")).raised
    res = run_notebook(monkeypatch, ws, install_widgets(central_workspaces="none"))
    assert not res.raised, res.status
    scan = [j for j in ws.jobs.values() if j.tags["role"] == "scan"][0]
    params = {p.name: p.default for p in scan.parameters}
    assert params["central_workspaces"] == "" and params["central_secret"] == ""


def test_a_target_you_cant_see_is_a_note_not_a_crash(monkeypatch):
    ws = FakeWS()
    real_make = ws.make

    def make():
        client = real_make()
        get = client.schemas.get

        def schemas_get(full):
            if full == "main.ug_migrated":
                raise sdk_errors.PermissionDenied("User does not have USE SCHEMA on Schema 'main.ug_migrated'")
            return get(full)
        client.schemas.get = schemas_get
        return client
    ws.make = make
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert not res.raised, res.status
    assert "[NOTE] Schema for new model services: couldn't check main.ug_migrated" in res.text


def test_uninstall_results_schema_must_be_catalog_dot_schema(monkeypatch):
    ws = FakeWS()
    seed_install(ws)
    res = run_notebook(monkeypatch, ws, uninstall_widgets("uninstall: preview", results_schema="main"))
    assert res.raised and "6. Results schema must be catalog.schema" in res.status


# ---------------------------------------------------------------------------------------------------------------------
# Central mode setup, from a customer's first install (Azure): the name vs ID, the secret, and the network policies

def test_resolve_run_as_takes_a_name_or_an_application_id():
    f = H["resolve_run_as"]
    look = lambda n: [("ugmig-central", SP_ID), ("UGMIG-central", SP_ID), ("other", "x")]
    assert f(SP_ID, look) == (SP_ID, None, None)
    assert f("", look) == ("", None, None)
    got, note, problem = f("ugmig-central", look)
    assert got == SP_ID and "is application ID" in note and problem is None
    assert "no service principal named 'nope'" in f("nope", lambda n: [])[2]
    two = f("dup", lambda n: [("dup", SP_ID), ("dup", "aaaaaaaa-0000-0000-0000-000000000009")])[2]
    assert "2 service principals are named 'dup'" in two
    broken = f("x", lambda n: (_ for _ in ()).throw(RuntimeError("forbidden")))[2]
    assert "couldn't look up" in broken and "application ID" in broken


def test_run_as_by_name_is_resolved_and_the_jobs_get_the_id(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets(run_as="ugmig-central"))
    assert not res.raised, res.status
    assert f"run_as: ugmig-central is application ID {SP_ID}" in res.text
    assert all(j.run_as == jobs.JobRunAs(service_principal_name=SP_ID) for j in ws.jobs.values())


def _central(**kw):
    return install_widgets(run_as=SP_ID, central_workspaces="2222222222222222", central_secret="s/k", **kw)


def test_central_mode_checks_the_secret_and_says_what_the_network_needs(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, _central())
    assert not res.raised, res.status
    assert f"[OK  ] Central mode secret: s/k exists and {SP_ID} can read it" in res.text
    note = [l for l in res.text.splitlines() if "[NOTE] Central mode network" in l][0]
    for part in ("serverless compute", "2222222222222222", "Cross Workspace Network Policy", "Compatibility mode",
                 "ingress policies", "allows all destinations", "Cert validation failed", "classic compute",
                 "workspace admin"):
        assert part in note, part


@pytest.mark.parametrize("setup, expect", [
    (lambda ws: ws.secret_scopes.clear(), "the secret scope 's' doesn't exist"),
    (lambda ws: ws.secret_scopes.__setitem__("s", {"other"}), "the secret scope s has no key 'k'"),
    (lambda ws: ws.secret_acls.clear(), f"service principal {SP_ID} can't read the secret scope s. Give it READ: "
                                        f"databricks secrets put-acl s {SP_ID} READ"),
])
def test_central_mode_secret_problems_stop_the_install_with_the_command(monkeypatch, setup, expect):
    ws = FakeWS()
    setup(ws)
    res = run_notebook(monkeypatch, ws, _central())
    assert res.raised and expect in res.status, res.status
    assert not ws.apps


def test_install_call_documents_central_service_principal_settings():
    text = _notebook_text("install")
    assert "Databricks OAuth secret" in text and "not an Entra ID secret" in text
    assert "name or application ID" in text
