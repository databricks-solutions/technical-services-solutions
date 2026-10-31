# Databricks notebook source
# MAGIC %md
# MAGIC # Install the Unity Gateway Migration Toolkit
# MAGIC
# MAGIC This one notebook installs everything inside this workspace: no CLI, no Git, no local setup.
# MAGIC
# MAGIC 1. Fill in the widgets at the top (only **Results catalog** and **SQL warehouse** usually need a change).
# MAGIC 2. Click **Run all**. It takes about 5 minutes; the link to the app is printed at the end.
# MAGIC
# MAGIC What it creates (the jobs are tagged `Project = unity-gateway-migration-toolkit`, so the usage of this toolkit can be identified):
# MAGIC - The toolkit files in the **Install folder** (replaced on every run, so files removed from a newer version don't linger).
# MAGIC - The results schema (if it doesn't exist).
# MAGIC - Three Lakeflow jobs the app starts: account snapshot (weekly schedule, paused), workspace scan, and apply/rollback.
# MAGIC - The **Unity Gateway Migration Toolkit** app (charts and exports are in the app).
# MAGIC
# MAGIC **Before anything is changed**, the notebook checks the workspace (Apps, catalog and schema privileges, the SQL
# MAGIC warehouse, system tables, the install folder, and whether another toolkit install already uses the same app name,
# MAGIC results schema or folder). If a check fails, it stops and says what to change.
# MAGIC
# MAGIC **Who the jobs run as:** you (the person running this notebook). Scans and apply act with your permissions, so
# MAGIC run it as a workspace admin with access to the system tables, or as a service principal for a shared install
# MAGIC (for a service principal, set **Operators** explicitly).
# MAGIC Only the people in **Operators** can start jobs from the app; everyone else can only view results.
# MAGIC
# MAGIC Run it again to update (same widgets). To remove it, set **Action** to `uninstall` and choose what else goes
# MAGIC with the three **Uninstall:** widgets (results tables, apply logs, Unity Gateway services created by apply).
# MAGIC The first uninstall run only shows what would be removed and what would be kept; set **Uninstall: confirm** to
# MAGIC `yes` and run it again to remove. Uninstall refuses while an apply run is active.
# MAGIC
# MAGIC Prototype from Databricks Shared Technical Services, provided as is. Version __VERSION__.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk==0.158.0"
# MAGIC %restart_python

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
me_user = w.current_user.me()
me = me_user.user_name
warehouses = sorted(w.warehouses.list(), key=lambda x: (x.state is None or x.state.value != "RUNNING", x.name or ""))
wh_choices = [f"{x.name} ({x.id})" for x in warehouses] or ["<no SQL warehouse found>"]

dbutils.widgets.dropdown("action", "install", ["install", "uninstall"], "1. Action")
dbutils.widgets.text("results_catalog", "main", "2. Results catalog (must exist)")
dbutils.widgets.text("results_schema", "", "3. Results schema (blank = ug_migration, or ug_migration_<app name>)")
dbutils.widgets.dropdown("warehouse", wh_choices[0], wh_choices, "4. SQL warehouse")
dbutils.widgets.text("operators", "", "5. Operators (emails, comma-separated; blank = you)")
dbutils.widgets.text("app_name", "unity-gateway-migration", "6. App name (2-30 characters)")
dbutils.widgets.text("install_folder", "", "7. Install folder (blank = your home folder, <app name>-toolkit)")
dbutils.widgets.dropdown("adopt_app", "no", ["no", "yes"], "8. Adopt existing app (replace an app that isn't a toolkit app)")
dbutils.widgets.dropdown("allow_downgrade", "no", ["no", "yes"], "9. Allow downgrade (older version over a newer one)")
dbutils.widgets.dropdown("second_install", "no", ["no", "yes"], "10. Allow a second install (other app name, results and folder)")
dbutils.widgets.text("secret_schemas", "", "11. Allowed secret schemas (catalog.schema, comma-separated; blank = off)")
dbutils.widgets.dropdown("allow_secret_read", "no", ["no", "yes"], "12. Allow reading secret values")
dbutils.widgets.dropdown("drop_data", "no", ["no", "yes"], "13. Uninstall: remove results tables (and the schema, if empty)")
dbutils.widgets.dropdown("remove_logs", "no", ["no", "yes"], "14. Uninstall: remove apply logs")
dbutils.widgets.dropdown("rollback_services", "no", ["no", "yes"], "15. Uninstall: roll back Unity Gateway services created by apply")
dbutils.widgets.dropdown("confirm_uninstall", "no", ["no", "yes"], "16. Uninstall: confirm (no = only show what would be removed)")

# COMMAND ----------

# HELPERS-BEGIN
# Pure helpers: no workspace calls. test_installer.py runs this block, so keep it free of dbutils, spark and w.
import base64
import dataclasses
import io
import json
import re
import zipfile
from datetime import timedelta

from databricks.sdk.service import apps, jobs
from databricks.sdk.service.workspace import ImportFormat, Language

TOOL_TAG = "ug-migration-toolkit"
PROJECT_TAG = "unity-gateway-migration-toolkit"
APP_MARKER = "Unity Gateway Migration Toolkit"  # every toolkit app's description starts with this
LEGACY_APP = "unity-gateway-migration"  # the app name the installer has used by default since 0.8.0
NAME = r"[A-Za-z0-9_]+"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# App fields the API fills in. They are not sent back on update.
APP_OUTPUT_ONLY = {
    "active_deployment", "app_status", "compute_status", "create_time", "creator", "default_git_source",
    "default_source_code_path", "effective_budget_policy_id", "effective_usage_policy_id",
    "effective_user_api_scopes", "id", "oauth2_app_client_id", "oauth2_app_integration_id", "pending_deployment",
    "service_principal_client_id", "service_principal_id", "service_principal_name", "update_time", "updater", "url"}
SNAPSHOT_CRON = "0 0 6 ? * MON"


def split_list(raw: str) -> list[str]:
    return list(dict.fromkeys(x.strip() for x in (raw or "").split(",") if x.strip()))


def valid_folder(path: str) -> str | None:
    """Problem with an install folder, or None."""
    if not re.fullmatch(r"/Workspace/(Users|Shared)/[^.][^\n]*", path):
        return "install folder must look like /Workspace/Users/<you>/<folder> or /Workspace/Shared/<folder>"
    if any(s in ("", ".", "..") for s in path.split("/")[1:]):
        return "install folder can't contain '.', '..' or empty path segments"
    return None


def results_schema_for(raw: str, app_name: str) -> str:
    """Blank means ug_migration for the default app name (as before), else a schema named after the app."""
    raw = (raw or "").strip()
    if raw:
        return raw
    return "ug_migration" if app_name == LEGACY_APP else app_name.replace("-", "_")


def folder_for(raw: str, me: str, app_name: str) -> str:
    """Blank means a folder in your home folder named after the app (the default app name keeps the old folder)."""
    raw = (raw or "").strip().rstrip("/")
    return raw or f"/Workspace/Users/{me}/{app_name}-toolkit"


def is_service_principal(user_name: str) -> bool:
    return bool(re.fullmatch(UUID, user_name or ""))


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def downgrade_problem(prev: str, now: str, allow: bool) -> str | None:
    if prev and version_key(prev) > version_key(now) and not allow:
        return (f"this would downgrade the toolkit from {prev} to {now}; set Allow downgrade = yes to do it anyway")
    return None


def parse_marker(text: str) -> dict:
    """The install marker is JSON since 0.8.1. The older marker is a plain line, so it has no version."""
    try:
        d = json.loads(text)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def marker_text(app_name: str, version: str, results: str, folder: str, who: str) -> str:
    return json.dumps({"app": app_name, "version": version, "results": results, "folder": folder,
                       "installed_by": who}, indent=2) + "\n"


def is_toolkit_app(description: str | None) -> bool:
    return (description or "").startswith(APP_MARKER)


def app_from_job(name: str | None, tags: dict) -> str:
    """The app a toolkit job belongs to: its app tag, or the [app] prefix of the name (0.7 jobs)."""
    m = re.match(r"\[(.+?)\] Unity Gateway migration", name or "")
    return tags.get("app") or (m.group(1) if m else "")


def parse_secret_schemas(raw: str) -> tuple[list[str], str | None]:
    schemas = split_list(raw)
    bad = [s for s in schemas if not re.fullmatch(rf"{NAME}\.{NAME}", s)]
    if bad:
        return schemas, "allowed secret schemas must be catalog.schema, comma-separated: " + ", ".join(bad)
    return schemas, None


def install_folder_of(notebook_path: str) -> str:
    """The install folder a toolkit notebook lives in (<folder>/files/notebook/...)."""
    return notebook_path.split("/files/", 1)[0] if "/files/" in notebook_path else ""


def overlaps(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or a.startswith(b + "/") or b.startswith(a + "/"))


def shared_state(others: list[dict], results: str, folder: str) -> list[dict]:
    """Other installs (dicts with app, results, folder) that use this results schema or install folder."""
    out = []
    for o in others:
        if o.get("results") and o["results"].lower() == results.lower():
            out.append({"kind": "results", "app": o["app"]})
        if overlaps(o.get("folder", ""), folder):
            out.append({"kind": "folder", "app": o["app"]})
    return out


def job_settings(app_name: str, role: str, title: str, notebook_path: str, params: list, **extra) -> jobs.JobSettings:
    return jobs.JobSettings(
        name=f"[{app_name}] Unity Gateway migration {title}",
        tags={"tool": TOOL_TAG, "Project": PROJECT_TAG, "app": app_name, "role": role},
        parameters=params, max_concurrent_runs=1,
        tasks=[jobs.Task(task_key=role, notebook_task=jobs.NotebookTask(notebook_path=notebook_path))],
        **extra)


def job_specs(app_name: str, folder: str, results: str, warehouse_id: str, secret_schemas: list[str],
              allow_secret_read: bool) -> dict[str, jobs.JobSettings]:
    """The three toolkit jobs. Parameter names match the notebooks in notebook/ and the bundle's databricks.yml."""
    P = jobs.JobParameterDefinition
    files = f"{folder}/files"
    return {
        "snapshot": job_settings(app_name, "snapshot", "snapshot", f"{files}/notebook/run_account", [
            P("days", "30"), P("snapshot_table", f"{results}.ug_migration"), P("out_dir", f"{folder}/output/account"),
            P("deep_scan", "0"), P("deep_warehouse_id", warehouse_id), P("requested_by", "schedule")],
            schedule=jobs.CronSchedule(quartz_cron_expression=SNAPSHOT_CRON, timezone_id="UTC",
                                       pause_status=jobs.PauseStatus.PAUSED)),
        "scan": job_settings(app_name, "scan", "workspace scan", f"{files}/notebook/run_scan", [
            P("run_id", ""), P("job_run_id", "{{job.run_id}}"), P("results_schema", results), P("days", "30"),
            P("scan_roots", ""), P("target_catalog", "ai_gateway"), P("target_schema", "migrated"),
            P("requested_by", "")]),
        "apply": job_settings(app_name, "apply", "apply", f"{files}/notebook/run_apply", [
            P("apply_id", ""), P("job_run_id", "{{job.run_id}}"), P("results_schema", results), P("mode", "dry_run"),
            P("endpoints", ""), P("target_catalog", ""), P("target_schema", ""), P("uc_secret_map", ""),
            P("allow_secret_read", "false"), P("grants", "true"), P("rollback_of", ""), P("scan_run_id", ""),
            P("requested_by", ""),
            P("secret_schemas", ",".join(secret_schemas)),
            P("allow_secret_read_enabled", "true" if allow_secret_read else "false"),
            P("ack_guardrails", "false")]),
    }


def app_resources(warehouse_id: str, job_ids: dict[str, int]) -> list[apps.AppResource]:
    R = apps.AppResource
    return [
        R(name="sql-warehouse", sql_warehouse=apps.AppResourceSqlWarehouse(
            id=warehouse_id, permission=apps.AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE)),
        *[R(name=f"{role}-job", job=apps.AppResourceJob(id=str(job_ids[role]),
                                                         permission=apps.AppResourceJobJobPermission.CAN_MANAGE_RUN))
          for role in ("snapshot", "scan", "apply")],
    ]


def app_env(results: str, operators: list[str], version: str, secret_schemas: list[str],
            allow_secret_read: bool) -> list[apps.EnvVar]:
    E = apps.EnvVar
    return [
        E(name="DATABRICKS_WAREHOUSE_ID", value_from="sql-warehouse"),
        E(name="SNAPSHOT_JOB_ID", value_from="snapshot-job"), E(name="SCAN_JOB_ID", value_from="scan-job"),
        E(name="APPLY_JOB_ID", value_from="apply-job"), E(name="RESULTS_SCHEMA", value=results),
        E(name="SNAPSHOT_PREFIX", value="ug_migration"), E(name="OPERATORS", value=",".join(operators)),
        E(name="UGMIG_VERSION", value=version), E(name="UGMIG_SECRET_SCHEMAS", value=",".join(secret_schemas)),
        E(name="UGMIG_ALLOW_SECRET_READ", value="true" if allow_secret_read else "false"),
        E(name="UGMIG_MAX_SCAN_AGE_DAYS", value="14")]


def app_update_spec(existing: apps.App, **set_fields) -> apps.App:
    """The full App for apps.update (it replaces the app). Everything the API returned that the installer
    doesn't set (budget and usage policy, compute size, instances, space, git source...) is kept."""
    kept = {f.name: getattr(existing, f.name) for f in dataclasses.fields(apps.App) if f.name not in APP_OUTPUT_ONLY}
    kept.update(set_fields)
    return apps.App(**kept)
def uninstall_summary(drop: bool, remove_logs: bool, rollback: bool, pending: list[dict], has_logs: bool,
                      results: str, folder: str) -> tuple[list[str], list[str]]:
    """What an uninstall removes and keeps. pending: execute runs not rolled back yet (apply_id, created)."""
    created = sum(p.get("created", 0) for p in pending)
    remove = ["the app and its three jobs", f"the toolkit files and snapshot output in {folder}"]
    keep = []
    if pending and rollback:
        remove.insert(0, f"Unity Gateway services and grants created by {len(pending)} apply run(s) "
                         f"({created} object(s)), rolled back newest first before anything else is removed")
    elif pending:
        keep.append(f"Unity Gateway services created by {len(pending)} apply run(s) ({created} object(s)): callers "
                    "that moved to them keep working (set Uninstall: roll back ... = yes to remove them)")
    else:
        keep.append("no Unity Gateway services: no apply run created any that is still in place")
    (remove if drop else keep).append(f"the results tables in {results}" + (" (and the schema, if nothing else is in it)"
                                                                            if drop else ""))
    if has_logs:
        (remove if remove_logs else keep).append(f"the apply logs in {folder}/apply_logs")
        if remove_logs and pending and not rollback:
            keep.append("WARNING: without the apply logs and the app, the kept services can only be removed by hand")
    return remove, keep


# HELPERS-END

# COMMAND ----------

g = dbutils.widgets.get
ACTION = g("action")
CATALOG = g("results_catalog").strip()
APP_NAME = g("app_name").strip()
SCHEMA = results_schema_for(g("results_schema"), APP_NAME)
RESULTS = f"{CATALOG}.{SCHEMA}"
m = re.search(r"\(([0-9a-f]+)\)$", g("warehouse"))
WAREHOUSE_ID = m.group(1) if m else ""
IS_SP = is_service_principal(me)
OPERATOR_LIST = split_list(g("operators"))
if not OPERATOR_LIST and not IS_SP:
    OPERATOR_LIST = [me]  # people: the signed-in user by default. Service principals must set it.
FOLDER = folder_for(g("install_folder"), me, APP_NAME)
FILES = f"{FOLDER}/files"
MARKER = f"{FOLDER}/ug_migration_toolkit.marker"
ADOPT = g("adopt_app") == "yes"
ALLOW_DOWNGRADE = g("allow_downgrade") == "yes"
SECOND_INSTALL = g("second_install") == "yes"
ALLOW_SECRET_READ = g("allow_secret_read") == "yes"
SECRET_SCHEMAS, secret_problem = parse_secret_schemas(g("secret_schemas"))
TOOLKIT_VERSION = "__VERSION__"
APP_DESCRIPTION = f"{APP_MARKER}: account overview, workspace scans, readiness, code fixes and apply"
DROP = g("drop_data") == "yes"
REMOVE_LOGS = g("remove_logs") == "yes"
ROLLBACK = g("rollback_services") == "yes"
CONFIRMED = g("confirm_uninstall") == "yes"
SCHEMA_GIVEN = bool(g("results_schema").strip())
FOLDER_GIVEN = bool(g("install_folder").strip())

problems = []
if not re.fullmatch(NAME, CATALOG):
    problems.append("results catalog must use letters, digits and underscores")
if not re.fullmatch(NAME, SCHEMA):
    problems.append("results schema must use letters, digits and underscores")
if not re.fullmatch(r"[a-z0-9-]{2,30}", APP_NAME):
    problems.append("app name: 2-30 lowercase letters, digits or hyphens")
if valid_folder(FOLDER):
    problems.append(valid_folder(FOLDER))
if secret_problem:
    problems.append(secret_problem)
if ACTION == "install" and not WAREHOUSE_ID:
    problems.append("choose a SQL warehouse")
if ACTION == "install" and IS_SP and not split_list(g("operators")):
    problems.append("this runs as a service principal, so set Operators explicitly (emails of the people who can start jobs in the app)")
if problems:
    raise ValueError("Fix the widgets: " + "; ".join(problems))

# COMMAND ----------

from databricks.sdk.errors import DatabricksError, NotFound, ResourceDoesNotExist
from databricks.sdk.service.workspace import ExportFormat

DASH_NAME = "Unity Gateway migration progress"  # created by versions before 0.8.0; the app replaces it


def get_app():
    try:
        return w.apps.get(APP_NAME)
    except (NotFound, ResourceDoesNotExist):
        return None


def find_dashboard_id() -> str | None:
    """The dashboard an earlier version of this installer created (the dashboards list API doesn't return paths)."""
    try:
        return w.workspace.get_status(f"{FOLDER}/{DASH_NAME}.lvdash.json").resource_id
    except (NotFound, ResourceDoesNotExist):
        return None


def toolkit_installs() -> list[dict]:
    """Every toolkit job in the workspace (matched on tags): app, role, job id, results schema and install folder."""
    out = []
    for j in w.jobs.list(expand_tasks=True):
        s = j.settings
        tags = (s.tags or {}) if s else {}
        if tags.get("tool") != TOOL_TAG:
            continue
        params = {p.name: p.default for p in (s.parameters or [])}
        path = s.tasks[0].notebook_task.notebook_path if s.tasks and s.tasks[0].notebook_task else ""
        out.append({"job_id": j.job_id, "app": app_from_job(s.name, tags), "role": tags.get("role", ""),
                    "results": params.get("results_schema", ""), "folder": install_folder_of(path)})
    return out


INSTALLS = toolkit_installs()  # read once; the install and uninstall cells below use it


def find_jobs() -> dict[str, list[int]]:
    """This app's jobs by role."""
    found: dict[str, list[int]] = {}
    for i in INSTALLS:
        if i["app"] == APP_NAME:
            found.setdefault(i["role"], []).append(i["job_id"])
    return found


def adopt_existing_locations() -> None:
    """A blank Results schema or Install folder keeps the one this app was installed with (earlier versions used
    other defaults), so an update doesn't split the install. Widgets with a value always win."""
    global CATALOG, SCHEMA, RESULTS, FOLDER, FILES, MARKER
    mine = [i for i in INSTALLS if i["app"] == APP_NAME]
    results = next((i["results"] for i in mine if i["results"]), "")
    folder = next((i["folder"] for i in mine if i["folder"]), "")
    if not SCHEMA_GIVEN and results and "." in results:
        CATALOG, SCHEMA = results.split(".", 1)
        RESULTS = results
        print("using the results schema of the existing install:", RESULTS)
    if not FOLDER_GIVEN and folder:
        FOLDER = folder
        FILES = f"{FOLDER}/files"
        MARKER = f"{FOLDER}/ug_migration_toolkit.marker"
        print("using the install folder of the existing install:", FOLDER)
    print(f"{ACTION}: app {APP_NAME}, results {RESULTS}, warehouse {WAREHOUSE_ID}, folder {FOLDER}, "
          f"operators {', '.join(OPERATOR_LIST) or '(none)'}, jobs run as {me}")


adopt_existing_locations()


def run_sql(statement: str) -> str | None:
    """None if the statement succeeds on the chosen warehouse, else the error text."""
    r = w.statement_execution.execute_statement(statement=statement, warehouse_id=WAREHOUSE_ID, wait_timeout="50s")
    if r.status and r.status.state and r.status.state.value == "SUCCEEDED":
        return None
    if r.status and r.status.error:
        return r.status.error.message
    return f"state {r.status.state.value if r.status and r.status.state else 'unknown'}"


def can_use(securable: str, name: str, wanted: set[str]) -> bool:
    """Best effort: True if you, or one of your groups, holds one of the privileges on the securable."""
    principals = [me] + [gr.display for gr in (me_user.groups or []) if gr.display][:50]
    for p in principals:
        try:
            res = w.grants.get_effective(securable, name, principal=p)
        except DatabricksError:
            continue
        for a in res.privilege_assignments or []:
            if {x.privilege.value for x in (a.privileges or []) if x.privilege} & wanted:
                return True
    return False


def installed_version(existing) -> str:
    """The version of the install in the folder (marker), else the version the existing app was deployed with."""
    try:
        raw = w.workspace.export(MARKER, format=ExportFormat.RAW).content or ""
        marker = parse_marker(base64.b64decode(raw).decode(errors="replace"))
    except (NotFound, ResourceDoesNotExist):
        marker = {}
    if marker.get("version"):
        return marker["version"]
    if existing and existing.active_deployment and existing.active_deployment.env_vars:
        env = {e.name: e.value for e in existing.active_deployment.env_vars}
        return env.get("UGMIG_VERSION", "")
    return ""


def preflight() -> tuple[list[str], str]:
    """Read-only checks, run before anything is created, changed or deleted. Returns (problems, version note)."""
    found = []
    try:
        next(iter(w.apps.list(page_size=1)), None)
    except DatabricksError as e:
        return [f"Databricks Apps isn't usable here ({e}): check that Apps is enabled and you can create apps"], ""
    if valid_folder(FOLDER):
        found.append(valid_folder(FOLDER) + f" (install folder {FOLDER!r})")
    existing = get_app()
    if existing and not is_toolkit_app(existing.description) and not ADOPT:
        found.append(f"an app named {APP_NAME} exists and isn't a toolkit app: " + (
            "choose another App name, or set Adopt existing app = yes if it can be replaced" if ACTION == "install"
            else "uninstall won't delete it (set Adopt existing app = yes to do it anyway)"))
    # Other installs, by app name (jobs and apps), and what they share with this one.
    others = [i for i in INSTALLS if i["app"] != APP_NAME]
    for a in w.apps.list():
        if a.name != APP_NAME and is_toolkit_app(a.description):
            env = {e.name: e.value for e in (a.active_deployment.env_vars or [])} if a.active_deployment else {}
            others.append({"app": a.name, "results": env.get("RESULTS_SCHEMA", ""), "folder": ""})
    foreign = sorted({o["app"] for o in others if o["app"]})
    clash = shared_state(others, RESULTS, FOLDER)
    if ACTION == "install":
        if foreign and not SECOND_INSTALL:
            found.append("another toolkit install exists under app name " + ", ".join(foreign) + ": set App name to "
                         "that name to update it, or uninstall it first (to run two side by side, set Allow a second "
                         "install = yes, with other results and install folder)")
        for c in clash:
            found.append(f"{c['kind']} is used by the toolkit install of app {c['app']}: choose another "
                         f"{'results schema' if c['kind'] == 'results' else 'install folder'}")
        try:
            cat = w.catalogs.get(CATALOG)
        except (NotFound, ResourceDoesNotExist):
            return found + [f"results catalog {CATALOG!r} doesn't exist (or you can't see it): pick an existing catalog"], ""
        try:
            schema = w.schemas.get(RESULTS)
        except (NotFound, ResourceDoesNotExist):
            schema = None
            if cat.owner != me and not can_use("catalog", CATALOG, {"CREATE_SCHEMA", "ALL_PRIVILEGES"}):
                found.append(f"you can't create {RESULTS} (needs CREATE SCHEMA on {CATALOG}): pick a results schema "
                             "that exists and is writable, or ask for the privilege")
        if schema:
            owner_app = re.search(r"\(app: ([a-z0-9_-]+)\)", schema.comment or "")
            if owner_app and owner_app.group(1) != APP_NAME:
                found.append(f"results schema {RESULTS} belongs to app {owner_app.group(1)}: pick another results schema")
            elif schema.owner != me and not can_use("schema", RESULTS, {"ALL_PRIVILEGES", "CREATE_TABLE", "MODIFY"}):
                found.append(f"you can't write to {RESULTS} (needs CREATE TABLE and MODIFY, or ownership)")
        try:
            w.warehouses.get(WAREHOUSE_ID)
        except (NotFound, ResourceDoesNotExist):
            found.append("the SQL warehouse wasn't found: pick one in the widget")
        else:
            err = run_sql("SELECT 1 FROM system.serving.endpoint_usage LIMIT 1")
            if err:
                found.append(f"the SQL warehouse can't read system.serving.endpoint_usage (needs CAN USE on the "
                             f"warehouse and SELECT on system tables): {err}")
        # The app's own version check: an older toolkit over a newer one needs Allow downgrade.
        prev = installed_version(existing)
        note = f"version: {prev or 'unknown (no earlier version recorded)'} -> {TOOLKIT_VERSION}"
        problem = downgrade_problem(prev, TOOLKIT_VERSION, ALLOW_DOWNGRADE)
        if problem:
            found.append(problem)
    else:
        note = "uninstall"
        if clash and any(c["kind"] == "folder" for c in clash):
            found.append("uninstall would delete files that another install uses in the same folder: "
                         + ", ".join(c["app"] for c in clash if c["kind"] == "folder"))
        if DROP and any(c["kind"] == "results" for c in clash):
            found.append("removing the results tables would drop the results that another install uses: "
                         + ", ".join(c["app"] for c in clash if c["kind"] == "results")
                         + " (leave Uninstall: remove results tables = no)")
        for role, ids in find_jobs().items():
            for job_id in ids:
                if role == "apply" and next(iter(w.jobs.list_runs(job_id=job_id, active_only=True)), None):
                    found.append("an apply run is active: wait for it to finish (or cancel it in Jobs), then uninstall")
    return found, note


# Serverless job availability can't be checked with this SDK without starting a run, so the first scan or
# snapshot run is the check for that.
problems, version_note = preflight()
if problems:
    raise ValueError("Nothing was changed. Fix these first:\n- " + "\n- ".join(problems))
print(f"{ACTION}: {version_note}")

# COMMAND ----------

def pending_rollbacks() -> list[dict]:
    """Execute runs whose Unity Gateway objects are still in place (no successful rollback), newest first."""
    try:
        rows = spark.sql(f"""
            SELECT a.apply_id, count(i.payload) AS created FROM `{CATALOG}`.`{SCHEMA}`.ug_migration_applies a
            LEFT JOIN `{CATALOG}`.`{SCHEMA}`.ug_migration_apply_items i
              ON i.apply_id = a.apply_id AND get_json_object(i.payload, '$.action') = 'created'
            WHERE a.mode = 'execute' AND a.apply_id NOT IN (
              SELECT rollback_of FROM `{CATALOG}`.`{SCHEMA}`.ug_migration_applies
              WHERE mode = 'rollback' AND status = 'SUCCEEDED' AND rollback_of IS NOT NULL)
            GROUP BY a.apply_id, a.started_at ORDER BY a.started_at DESC""").collect()
    except Exception as e:  # no results tables yet: nothing was applied from this install
        if "TABLE_OR_VIEW_NOT_FOUND" in str(e) or "SCHEMA_NOT_FOUND" in str(e):
            return []
        raise
    return [{"apply_id": r["apply_id"], "created": r["created"]} for r in rows if r["created"]]


def rollback_status(apply_id: str) -> str:
    rows = spark.sql(f"SELECT status FROM `{CATALOG}`.`{SCHEMA}`.ug_migration_applies WHERE mode = 'rollback' "
                     f"AND rollback_of = '{apply_id}' ORDER BY started_at DESC LIMIT 1").collect()
    return rows[0]["status"] if rows else "not recorded"


if ACTION == "uninstall":
    existing = get_app()
    pending = pending_rollbacks()
    try:
        has_logs = bool(list(w.workspace.list(f"{FOLDER}/apply_logs")))
    except (NotFound, ResourceDoesNotExist):
        has_logs = False
    remove, keep = uninstall_summary(DROP, REMOVE_LOGS, ROLLBACK, pending, has_logs, RESULTS, FOLDER)
    print("Uninstall removes:\n- " + "\n- ".join(remove))
    print("Uninstall keeps:\n- " + "\n- ".join(keep))
    if not CONFIRMED:
        print("\nNothing was changed. Adjust the Uninstall: widgets if needed, set Uninstall: confirm = yes and run again.")
        dbutils.notebook.exit("uninstall preview: nothing changed")
    if ROLLBACK and pending:
        apply_jobs = find_jobs().get("apply") or []
        if not apply_jobs:
            raise ValueError("Nothing was removed: the apply job is missing, so services can't be rolled back here. "
                             "Roll them back with the command line (USER_GUIDE section 8), then uninstall.")
        for p in pending:  # newest first, so providers shared with earlier runs are removed by the last rollback
            print("rolling back apply", p["apply_id"], "...")
            try:
                w.jobs.run_now(job_id=apply_jobs[0], job_parameters={
                    "mode": "rollback", "rollback_of": p["apply_id"], "results_schema": RESULTS,
                    "requested_by": me}).result(timeout=timedelta(minutes=60))
            except Exception as e:  # the run failed or timed out; its row says how far it got
                print("rollback run ended with an error:", str(e)[:300])
            status = rollback_status(p["apply_id"])
            if status != "SUCCEEDED":
                raise ValueError(f"Uninstall stopped: the rollback of apply {p['apply_id']} ended {status} (see its "
                                 "results in the app). Rollbacks that finished stay done; nothing else was removed.")
    for role, ids in find_jobs().items():
        for job_id in ids:  # stop what's running before the jobs go (apply was checked above)
            w.jobs.cancel_all_runs(job_id=job_id)
    if existing:
        w.apps.delete(APP_NAME)
        print("deleted app", APP_NAME)
    for role, ids in find_jobs().items():
        for job_id in ids:
            w.jobs.delete(job_id)
            print("deleted job", role, job_id)
    dash = find_dashboard_id()
    if dash:
        w.lakeview.trash(dash)
        print("moved dashboard to Trash:", DASH_NAME)
    for path in (FILES, f"{FOLDER}/output", MARKER) + ((f"{FOLDER}/apply_logs",) if REMOVE_LOGS else ()):
        try:  # toolkit files, snapshot output files (results are in tables), the install marker, apply logs if chosen
            w.workspace.delete(path, recursive=True)
            print("deleted", path)
        except (NotFound, ResourceDoesNotExist):
            pass
    try:  # the install folder itself, if nothing else is left in it
        if not list(w.workspace.list(FOLDER)):
            w.workspace.delete(FOLDER)
            print("deleted", FOLDER)
    except (NotFound, ResourceDoesNotExist):
        pass
    if DROP:
        for t in ("scans", "scan_items", "applies", "apply_items", "workspaces", "endpoints"):
            spark.sql(f"DROP TABLE IF EXISTS `{CATALOG}`.`{SCHEMA}`.ug_migration_{t}")
        print("dropped results tables in", RESULTS)
        try:  # RESTRICT: only an empty schema goes
            spark.sql(f"DROP SCHEMA IF EXISTS `{CATALOG}`.`{SCHEMA}` RESTRICT")
            print("dropped schema", RESULTS)
        except Exception:
            print("kept schema", RESULTS, "(other objects are in it)")
    print("Done. Kept:\n- " + "\n- ".join(keep) if keep else "Done.")
    dbutils.notebook.exit("uninstalled")

# COMMAND ----------

# MAGIC %md ## 1. Toolkit files

# COMMAND ----------

PAYLOAD = "__PAYLOAD__"

# Replace the folder's files, so a file removed from a newer version doesn't stay behind.
try:
    w.workspace.delete(FILES, recursive=True)
except (NotFound, ResourceDoesNotExist):
    pass
w.workspace.mkdirs(FILES)
n = 0
with zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))) as z:
    for info in z.infolist():
        if info.is_dir():
            continue
        path = f"{FILES}/{info.filename}"
        w.workspace.mkdirs(path.rsplit("/", 1)[0])
        data = z.read(info)
        is_notebook = info.filename.startswith("notebook/") and data.startswith(b"# Databricks notebook source")
        target = path[: -len(".py")] if is_notebook else path
        if is_notebook:
            w.workspace.upload(target, io.BytesIO(data), format=ImportFormat.SOURCE, language=Language.PYTHON, overwrite=True)
        else:
            w.workspace.upload(target, io.BytesIO(data), format=ImportFormat.AUTO, overwrite=True)
        n += 1
print(f"wrote {n} files to {FILES}")

# COMMAND ----------

# MAGIC %md ## 2. Results schema

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}` COMMENT 'Unity Gateway migration app results (app: {APP_NAME})'")
spark.sql(f"COMMENT ON SCHEMA `{CATALOG}`.`{SCHEMA}` IS 'Unity Gateway migration app results (app: {APP_NAME})'")
print("schema ready:", RESULTS)

# COMMAND ----------

# MAGIC %md ## 3. Jobs

# COMMAND ----------

SPECS = job_specs(APP_NAME, FOLDER, RESULTS, WAREHOUSE_ID, SECRET_SCHEMAS, ALLOW_SECRET_READ)
existing = find_jobs()
JOB_IDS = {}
for role, settings in SPECS.items():
    if existing.get(role):
        keep, *extra = sorted(existing[role])
        if settings.schedule:  # keep the schedule's paused/unpaused state across updates
            current = w.jobs.get(keep).settings.schedule
            if current and current.pause_status:
                settings.schedule.pause_status = current.pause_status
        w.jobs.reset(keep, settings)
        JOB_IDS[role] = keep
        print("updated job", role, keep)
        for job_id in extra:  # left over from an interrupted earlier run
            w.jobs.delete(job_id)
            print("removed duplicate job", role, job_id)
    else:
        JOB_IDS[role] = w.jobs.create(**settings.as_shallow_dict()).job_id
        print("created job", role, JOB_IDS[role])

# COMMAND ----------

# MAGIC %md ## 4. App

# COMMAND ----------

resources = app_resources(WAREHOUSE_ID, JOB_IDS)
existing_app = get_app()
if existing_app:  # apps.update replaces the app, so it gets the full app with the fields this installer doesn't set
    w.apps.update(APP_NAME, app_update_spec(existing_app, name=APP_NAME, description=APP_DESCRIPTION,
                                            resources=resources, user_api_scopes=["sql"]))
    print("updated app", APP_NAME)
else:
    print("creating app (a few minutes)...")
    w.apps.create_and_wait(apps.App(name=APP_NAME, resources=resources, user_api_scopes=["sql"],
                                    description=APP_DESCRIPTION))
app = get_app()
if app.compute_status and app.compute_status.state and app.compute_status.state.value not in ("ACTIVE", "STARTING"):
    w.apps.start_and_wait(APP_NAME)

deployment = apps.AppDeployment(
    source_code_path=f"{FILES}/app",
    command=["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
    env_vars=app_env(RESULTS, OPERATOR_LIST, TOOLKIT_VERSION, SECRET_SCHEMAS, ALLOW_SECRET_READ))
print("deploying app...")
d = w.apps.deploy_and_wait(APP_NAME, deployment)
print("deployment:", d.status.state.value if d.status and d.status.state else d.status)

# COMMAND ----------

# The install marker records the version, so the next run can show from -> to and refuse a silent downgrade.
w.workspace.upload(MARKER, io.BytesIO(marker_text(APP_NAME, TOOLKIT_VERSION, RESULTS, FOLDER, me).encode()),
                   format=ImportFormat.AUTO, overwrite=True)
print(f"installed {TOOLKIT_VERSION} ({version_note})")

# COMMAND ----------

old_dash = find_dashboard_id()  # charts and exports now live in the app
if old_dash:
    w.lakeview.trash(old_dash)
    print("moved the dashboard from an earlier version to Trash:", DASH_NAME)

# COMMAND ----------

# MAGIC %md ## 5. Grants for app users
# MAGIC Users who open the app read results as themselves. Grant read access to the people or groups who should see
# MAGIC them (the exact statements for this install are printed at the end), for example:
# MAGIC
# MAGIC ```sql
# MAGIC GRANT USE CATALOG ON CATALOG <results catalog> TO `migration-team`;
# MAGIC GRANT USE SCHEMA, SELECT ON SCHEMA <results catalog>.<results schema> TO `migration-team`;
# MAGIC ```
# MAGIC
# MAGIC Also give them **CAN USE** on the app (Compute, Apps, the app, Permissions) and on the SQL warehouse.
# MAGIC Keep the results schema limited to the migration team: scans store matched code lines from every scanned folder.

# COMMAND ----------

app = w.apps.get(APP_NAME)
host = w.config.host.rstrip("/")
print("App:", app.url)
for r, i in JOB_IDS.items():
    print(f"Job ({r}):", f"{host}/jobs/{i}")
displayHTML(f"""
<h3>Unity Gateway Migration Toolkit is installed</h3>
<p><b>Open the app:</b> <a href="{app.url}" target="_blank">{app.url}</a></p>
<p>Jobs: {", ".join(f'<a href="{host}/jobs/{i}" target="_blank">{r}</a>' for r, i in JOB_IDS.items())}</p>
<p>First steps in the app: <b>Overview</b> (Refresh snapshot), then <b>Scans</b> (Start scan). Charts and CSV exports are in the app.
Operators: {", ".join(OPERATOR_LIST) or "(none)"}. Results: {RESULTS}. Version {TOOLKIT_VERSION}. The user guide is in {FILES}/USER_GUIDE.md.</p>
<p>To let others view results, run (replace <code>migration-team</code> with your group):<br>
<code>GRANT USE CATALOG ON CATALOG `{CATALOG}` TO `migration-team`;<br>
GRANT USE SCHEMA, SELECT ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `migration-team`;</code></p>
""")

# COMMAND ----------

# Also return the links as the notebook result, so they're visible when the installer runs as a job.
dbutils.notebook.exit(json.dumps({"app": app.url, "version": TOOLKIT_VERSION,
                                  "jobs": {r: f"{host}/jobs/{i}" for r, i in JOB_IDS.items()}}))
