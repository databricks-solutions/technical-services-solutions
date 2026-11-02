"""Offline tests for the installer notebook.

installer/install_template.py has two layers. The HELPERS block (between the HELPERS-BEGIN / HELPERS-END markers) is pure
and is tested directly. The rest of the notebook runs against FakeWS, an in-memory workspace: the tests build the notebook
the way make_installer.build does (a small test payload instead of the real files), then run its cells one by one, with
dbutils, spark, displayHTML and the Databricks SDK replaced by fakes. Nothing here talks to a workspace.
"""

import base64
import io
import json
import pathlib
import re
import time
import uuid
import zipfile
from types import SimpleNamespace

import databricks.sdk as sdk_pkg
import pytest
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


def test_downgrade_needs_widget_and_compares_numbers():
    assert H["downgrade_problem"]("0.8.0", "0.7.0", allow=False) is not None
    assert H["downgrade_problem"]("0.8.0", "0.7.0", allow=True) is None
    assert H["downgrade_problem"]("0.7.0", "0.8.0", allow=False) is None
    assert H["downgrade_problem"]("", "0.8.0", allow=False) is None
    assert H["downgrade_problem"]("0.10.0", "0.9.0", allow=False) is not None
    assert "Advanced: Allow downgrade" in H["downgrade_problem"]("0.8.0", "0.7.0", allow=False)


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
    assert "GRANT USE SCHEMA, CREATE SERVICE ON SCHEMA `ai_gateway`.`migrated`" in "\n".join(H["target_schema_lines"](ME))


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
        self.trashed = []
        self.log = []
        self.next_run = 500
        self.clock = 0

    # ---- seeding helpers
    def add_table(self, key, rows=()):
        self.tables[key] = list(rows)

    # ---- SQL emulation (spark.sql) on the results tables
    def sql(self, stmt):
        s = " ".join(stmt.split())
        self.log.append(("sql", s[:100]))
        rows = []
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
            rolled = {r["rollback_of"] for r in applies if r["mode"] == "rollback" and r["status"] == "SUCCEEDED"}
            for a in sorted(applies, key=lambda r: r["started_at"], reverse=True):
                if a["mode"] != "execute" or a["apply_id"] in rolled:
                    continue
                created = sum(1 for i in items if i["apply_id"] == a["apply_id"] and '"created"' in i["payload"])
                rows.append({"apply_id": a["apply_id"], "job_run_id": a["job_run_id"], "created": created})
        m = re.search(r"SELECT status FROM .*rollback_of = '([^']+)'", s)
        if m:
            hits = [r for r in self.tables.get(f"{self.results_schema()}.ug_migration_applies", [])
                    if r["mode"] == "rollback" and r["rollback_of"] == m[1]]
            rows = [{"status": hits[-1]["status"]}] if hits else []
        return _ns(collect=lambda: rows)

    def results_schema(self):
        return "main.ug_migration"

    def _rollback_row(self, apply_id, status):
        self.clock += 1
        self.tables.setdefault(f"main.ug_migration.ug_migration_applies", []).append(
            {"apply_id": f"rb-{self.clock}", "mode": "rollback", "rollback_of": apply_id, "status": status,
             "started_at": f"2026-11-01T10:{self.clock:02d}:00"})
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
                m = re.match(r"CREATE SCHEMA IF NOT EXISTS `(\w+)`\.`(\w+)`", s)
                if m:
                    if m[1] in ws.no_create:
                        err = f"[INSUFFICIENT_PERMISSIONS] User does not have CREATE SCHEMA on Catalog '{m[1]}'"
                    else:
                        ws.schemas.setdefault(f"{m[1]}.{m[2]}", {"owner": ws.me, "comment": ""})
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
                    return _ns(path=path, resource_id=None)
                raise sdk_errors.NotFound(path)

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
                return [_ns(job_id=jid, settings=s) for jid, s in ws.jobs.items()]

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
                if params.get("mode") == "rollback":
                    apply_id = params["rollback_of"]
                    script = ws.rollback_script.get(apply_id, ["SUCCEEDED"])
                    behaviour = script.pop(0) if len(script) > 1 else script[0]
                    ws.log.append(("rollback", apply_id, behaviour))
                    if behaviour == "TIMEOUT":
                        ws._rollback_row(apply_id, "RUNNING")
                    elif behaviour == "FAILED":
                        ws._rollback_row(apply_id, "FAILED")
                    else:
                        ws._rollback_row(apply_id, behaviour)
                    return FakeRun(ws.next_run, behaviour=behaviour, ws=ws)
                ws.next_run += 1
                ws.log.append(("run_now", job_id, dict(params)))
                return FakeRun(ws.next_run)

        class Apps:
            def list(self_inner, page_size=None):
                return list(ws.apps.values())

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
                return ws.apps[name]

            def create_and_wait(self_inner, app, **kw):
                ws.log.append(("create_app", app.name))
                app.compute_status = apps.ComputeStatus(state=apps.ComputeState.ACTIVE)
                app.url = f"https://{app.name}.example.app"
                ws.apps[app.name] = app
                return app

            def create_update_and_wait(self_inner, app_name, update_mask, app=None, timeout=None):
                # Like the real partial update: only the masked fields change.
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

        return _ns(current_user=Current(), catalogs=Catalogs(), schemas=Schemas(), warehouses=Warehouses(),
                   grants=Grants(), statement_execution=Statements(), workspace=Workspace(), lakeview=Lakeview(),
                   jobs=Jobs(), apps=Apps(), config=_ns(host="https://ws.example.com"))


def app_obj(name, desc=DESC, env=None):
    a = apps.App(name=name, description=desc, user_api_scopes=["sql"])
    a.compute_status = apps.ComputeStatus(state=apps.ComputeState.ACTIVE)
    a.url = f"https://{name}.example.app"
    if env is not None:
        a.active_deployment = apps.AppDeployment(env_vars=[apps.EnvVar(name=k, value=v) for k, v in env.items()])
    return a


def seed_install(ws, app=APP, folder=FOLDER, results="main.ug_migration", version="0.9.0", pending=(), logs=(),
                 tables=True, schema_comment=None):
    """A complete install made by the installer: app, jobs, schema, tables, marker, files and apply runs.
    pending: (apply_id, created_count, run_id) for execute runs that still have services in place."""
    ws.apps[app] = app_obj(app, env={"RESULTS_SCHEMA": results, "UGMIG_VERSION": version})
    ids = {}
    for role, title, nb in (("snapshot", "snapshot", "run_account"), ("scan", "workspace scan", "run_scan"),
                            ("apply", "apply", "run_apply")):
        params = [jobs.JobParameterDefinition("snapshot_table", f"{results}.ug_migration")] if role == "snapshot" else [
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
    ws.files[f"{folder}/{'ug_migration_toolkit.marker'}"] = json.dumps(
        {"app": app, "version": version, "results": results, "folder": folder, "installed_by": ME}).encode()
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


def _notebook_text():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:  # a stand-in for the real payload
        z.writestr("notebook/run_account.py", "# Databricks notebook source\nprint('account')\n")
        z.writestr("notebook/run_scan.py", "# Databricks notebook source\nprint('scan')\n")
        z.writestr("notebook/run_apply.py", "# Databricks notebook source\nprint('apply')\n")
        z.writestr("USER_GUIDE.md", "guide\n")
        z.writestr("app/backend/main.py", "app = None\n")
    payload = base64.b64encode(buf.getvalue()).decode()
    return TEXT.replace("__VERSION__", "0.9.0").replace("__PAYLOAD__", payload)


class Outcome:
    def __init__(self, status, out, ws, labels):
        self.status, self.out, self.ws, self.labels = status, out, ws, labels

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
    """Runs the notebook cell by cell. Widgets not given keep the notebook's own defaults."""
    monkeypatch.setattr(sdk_pkg, "WorkspaceClient", lambda *a, **k: ws.make())
    text = _notebook_text()
    cells = text.split("\n# COMMAND ----------\n")
    vals = dict(widgets or {})
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
            return vals[name]

    def exit_(value):
        raise NBExit(value)

    ns = {
        "dbutils": _ns(widgets=Widgets(), notebook=_ns(exit=exit_)),
        "displayHTML": lambda html: out.append(re.sub(r"<[^>]+>", " ", html)),
        "spark": _ns(sql=ws.sql),
        "print": lambda *a, **k: out.append(" ".join(str(x) for x in a)),
    }
    status = "completed"
    try:
        for i, cell in enumerate(cells):
            exec(compile(cell, f"cell{i}", "exec"), ns)
    except NBExit as e:
        status = "exit: " + str(e.args[0])
    except Exception as e:  # noqa: BLE001 (the notebook's own failures are the result under test)
        status = f"raised {type(e).__name__}: {e}"
    return Outcome(status, out, ws, labels)


def install_widgets(**kw):
    return {"action": "install", "results_catalog": "main", "warehouse": WH_LABEL, **kw}


def uninstall_widgets(action="uninstall: remove", **kw):
    return {"action": action, "results_catalog": "main", "warehouse": WH_LABEL, **kw}


def snapshot_of(ws):
    return {"apps": sorted(ws.apps), "jobs": sorted(j.name for j in ws.jobs.values()), "schemas": sorted(ws.schemas),
            "tables": sorted(ws.tables), "files": sorted(ws.files)}


def test_widgets_are_the_first_code_cell_and_the_prompt_follows():
    cells = TEXT.split("\n# COMMAND ----------\n")
    assert cells[0].startswith("# Databricks notebook source")
    assert "Installing and using the app needs no CLI" in cells[0]
    assert 'dbutils.widgets.dropdown("action", "install", ["install", "uninstall: preview", "uninstall: remove"]' in cells[1]
    assert "confirm_uninstall" not in TEXT
    assert cells[2].strip().endswith("Set Install: Results catalog and SQL warehouse above, then Run all")
    assert "# MAGIC %pip" in cells[3]


def test_widget_labels_carry_their_prefix_and_the_rules(monkeypatch):
    lab = run_notebook(monkeypatch, FakeWS(), install_widgets()).labels
    for key in ("results_catalog", "warehouse", "operators", "app_name"):
        assert lab[key].startswith("Install:"), key
    for key in ("results_schema", "install_folder", "adopt_app", "allow_downgrade", "second_install", "secret_schemas",
                "allow_secret_read"):
        assert lab[key].startswith("Advanced:"), key
    for key in ("drop_data", "remove_logs", "rollback_services"):
        assert lab[key].startswith("Uninstall:"), key
    assert "2-30 lowercase letters, digits or hyphens" in lab["app_name"]
    assert "blank = ug_migration for the default app, else the app name with - as _" in lab["results_schema"]
    assert "blank = your home folder/<app name> (ending -toolkit)" in lab["install_folder"]
    assert "overwrites or deletes that app" in lab["adopt_app"]
    assert "risk" in lab["allow_secret_read"]


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
    assert "Advanced: Allowed secret schemas" in text  # how to turn on secret mapping
    # The apply target doesn't exist in this workspace: the exact SQL is printed and nothing is created for it.
    assert "CREATE SCHEMA IF NOT EXISTS `ai_gateway`.`migrated`;" in text
    assert "GRANT USE SCHEMA, CREATE SERVICE ON SCHEMA `ai_gateway`.`migrated`" in text
    assert "ai_gateway.migrated" not in ws.schemas and "ai_gateway.migrated" not in ws.catalogs


def test_install_refuses_without_a_catalog_and_changes_nothing(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, {"action": "install", "warehouse": WH_LABEL})
    assert res.raised and "choose Install: Results catalog" in res.status
    assert snapshot_of(ws) == snapshot_of(FakeWS()) and not ws.apps


def test_several_warehouses_need_a_choice_and_one_is_preselected(monkeypatch):
    ws = FakeWS()
    ws.warehouses["ffff0000"] = {"name": "other", "state": "RUNNING"}
    res = run_notebook(monkeypatch, ws, {"action": "install", "results_catalog": "main"})
    assert res.raised and "choose Install: SQL warehouse" in res.status
    assert not ws.apps
    ws2 = FakeWS()  # one warehouse: no choice needed
    res2 = run_notebook(monkeypatch, ws2, {"action": "install", "results_catalog": "main"})
    assert not res2.raised, res2.status
    assert APP in ws2.apps


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
    assert res.raised and "deployed by the bundle" in res.status and "Adopt existing app" in res.status
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
    res = run_notebook(monkeypatch, ws, uninstall_widgets(drop_data="yes"))
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


def test_legacy_deadline_widget_is_labelled_validated_and_passed_on(monkeypatch):
    ws = FakeWS()
    res = run_notebook(monkeypatch, ws, install_widgets(deadline="next spring"))
    assert res.raised and "Legacy deadline must be a date as YYYY-MM-DD" in res.status
    assert not ws.apps  # nothing created for a bad date
    res2 = run_notebook(monkeypatch, ws, install_widgets(deadline="2027-06-01"))
    assert not res2.raised, res2.status
    assert res2.labels["deadline"].startswith("Advanced:")
    env = {e.name: e.value for e in ws.apps[APP].active_deployment.env_vars}
    assert env["UGMIG_DEADLINE"] == "2027-06-01"
    snap = [j for j in ws.jobs.values() if j.tags["role"] == "snapshot"][0]
    assert {p.name: p.default for p in snap.parameters}["deadline"] == "2027-06-01"


def test_service_principal_install_needs_operators(monkeypatch):
    ws = FakeWS(me="0b1f7c2e-1234-4abc-9def-0123456789ab")
    res = run_notebook(monkeypatch, ws, install_widgets())
    assert res.raised and "set Install: Operators" in res.status
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
    assert by_role["scan"]["target_schema"] == "migrated"



def test_update_changes_only_the_fields_the_installer_owns():
    ns = H
    assert ns["APP_UPDATE_MASK"] == "description,resources,user_api_scopes"
