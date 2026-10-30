# Databricks notebook source
# MAGIC %md
# MAGIC # Install the Unity Gateway Migration app
# MAGIC
# MAGIC This one notebook installs everything inside this workspace: no CLI, no Git, no local setup.
# MAGIC
# MAGIC 1. Fill in the widgets at the top (only **Results catalog** and **SQL warehouse** usually need a change).
# MAGIC 2. Click **Run all**. It takes about 5 minutes; the link to the app is printed at the end.
# MAGIC
# MAGIC What it creates (all tagged `tool = ug-migration-toolkit`):
# MAGIC - The toolkit files in the **Install folder**.
# MAGIC - The results schema (if it doesn't exist).
# MAGIC - Three Lakeflow jobs the app starts: account snapshot (weekly schedule, paused), workspace scan, and apply/rollback.
# MAGIC - The **Unity Gateway Migration** app and the progress dashboard.
# MAGIC
# MAGIC **Who the jobs run as:** you (the person running this notebook). Scans and apply act with your permissions, so
# MAGIC run it as a workspace admin with access to the system tables, or as a service principal for a shared install.
# MAGIC Only the people in **Operators** can start jobs from the app; everyone else can only view results.
# MAGIC
# MAGIC Run it again to update (same widgets). Set **Action** to `uninstall` to remove the app, jobs and dashboard
# MAGIC (results tables are kept unless **Drop results tables** is `yes`).
# MAGIC
# MAGIC Prototype from Databricks Shared Technical Services, provided as is. Version __VERSION__.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk>=0.158.0"
# MAGIC %restart_python

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
me = w.current_user.me().user_name
warehouses = sorted(w.warehouses.list(), key=lambda x: (x.state is None or x.state.value != "RUNNING", x.name or ""))
wh_choices = [f"{x.name} ({x.id})" for x in warehouses] or ["<no SQL warehouse found>"]

dbutils.widgets.dropdown("action", "install", ["install", "uninstall"], "1. Action")
dbutils.widgets.text("results_catalog", "main", "2. Results catalog (must exist)")
dbutils.widgets.text("results_schema", "ug_migration", "3. Results schema")
dbutils.widgets.dropdown("warehouse", wh_choices[0], wh_choices, "4. SQL warehouse")
dbutils.widgets.text("operators", me, "5. Operators (emails, comma-separated)")
dbutils.widgets.text("app_name", "ug-migration", "6. App name")
dbutils.widgets.text("install_folder", f"/Workspace/Users/{me}/ug-migration-toolkit", "7. Install folder")
dbutils.widgets.dropdown("drop_data", "no", ["no", "yes"], "8. Drop results tables (uninstall)")

# COMMAND ----------

import base64
import io
import json
import re
import zipfile

from databricks.sdk.errors import NotFound, ResourceDoesNotExist
from databricks.sdk.service import apps, jobs
from databricks.sdk.service.dashboards import Dashboard
from databricks.sdk.service.workspace import ImportFormat, Language

g = dbutils.widgets.get
ACTION = g("action")
CATALOG, SCHEMA = g("results_catalog").strip(), g("results_schema").strip()
RESULTS = f"{CATALOG}.{SCHEMA}"
m = re.search(r"\(([0-9a-f]+)\)$", g("warehouse"))
WAREHOUSE_ID = m.group(1) if m else ""
OPERATORS = ",".join(e.strip() for e in g("operators").split(",") if e.strip())
APP_NAME = g("app_name").strip()
FOLDER = g("install_folder").rstrip("/")
FILES = f"{FOLDER}/files"
TAG = {"tool": "ug-migration-toolkit"}
JOB_PREFIX = f"[{APP_NAME}] Unity Gateway migration"

problems = []
for label, v in (("results catalog", CATALOG), ("results schema", SCHEMA)):
    if not re.fullmatch(r"[A-Za-z0-9_]+", v):
        problems.append(f"{label} must use letters, digits and underscores")
if not re.fullmatch(r"[a-z0-9-]{2,26}", APP_NAME):
    problems.append("app name: 2-26 lowercase letters, digits or hyphens")
if not FOLDER.startswith("/Workspace/"):
    problems.append("install folder must start with /Workspace/")
if ACTION == "install" and not WAREHOUSE_ID:
    problems.append("choose a SQL warehouse")
if problems:
    raise ValueError("Fix the widgets: " + "; ".join(problems))
if ACTION == "install":
    try:
        w.catalogs.get(CATALOG)
    except (NotFound, ResourceDoesNotExist):
        raise ValueError(f"Results catalog {CATALOG!r} doesn't exist (or you can't see it): pick an existing catalog")
print(f"{ACTION}: app {APP_NAME}, results {RESULTS}, warehouse {WAREHOUSE_ID}, folder {FOLDER}, jobs run as {me}")

# COMMAND ----------

def find_jobs() -> dict[str, list[int]]:
    """This install's jobs by role (matched on tags; the jobs list API only filters on exact names)."""
    found: dict[str, list[int]] = {}
    for role, title in (("snapshot", "snapshot"), ("scan", "workspace scan"), ("apply", "apply")):
        for j in w.jobs.list(name=f"{JOB_PREFIX} {title}"):
            tags = (j.settings.tags or {}) if j.settings else {}
            if tags.get("tool") == TAG["tool"] and tags.get("app") == APP_NAME:
                found.setdefault(role, []).append(j.job_id)
    return found


DASH_NAME = "Unity Gateway migration progress"


def find_dashboard_id() -> str | None:
    """The dashboard this installer created (the dashboards list API doesn't return paths)."""
    try:
        return w.workspace.get_status(f"{FOLDER}/{DASH_NAME}.lvdash.json").resource_id
    except (NotFound, ResourceDoesNotExist):
        return None


def get_app():
    try:
        return w.apps.get(APP_NAME)
    except (NotFound, ResourceDoesNotExist):
        return None


if ACTION == "uninstall":
    if get_app():
        w.apps.delete(APP_NAME)
        print("deleted app", APP_NAME)
    for role, ids in find_jobs().items():
        for job_id in ids:
            w.jobs.delete(job_id)
            print("deleted job", role, job_id)
    if find_dashboard_id():
        w.lakeview.trash(find_dashboard_id())
        print("moved dashboard to Trash:", DASH_NAME)
    for path in (FILES, f"{FOLDER}/output", f"{FOLDER}/ug_migration_toolkit.marker"):
        try:  # toolkit files, snapshot output files (results are in tables) and the install marker
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
    if g("drop_data") == "yes":
        for t in ("scans", "scan_items", "applies", "apply_items", "workspaces", "endpoints"):
            spark.sql(f"DROP TABLE IF EXISTS `{CATALOG}`.`{SCHEMA}`.ug_migration_{t}")
        print("dropped results tables in", RESULTS)
    print(f"Done. Kept: {FOLDER}/apply_logs (if any) and the Unity Gateway services created by apply (roll them back "
          "before uninstalling if you want them removed, since this run deletes the app)"
          + ("." if g("drop_data") == "yes" else f", and the results tables in {RESULTS}."))
    dbutils.notebook.exit("uninstalled")

# COMMAND ----------

# MAGIC %md ## 1. Toolkit files

# COMMAND ----------

PAYLOAD = "__PAYLOAD__"

w.workspace.mkdirs(FILES)
# Marks the install so workspace scans skip the toolkit's own files and outputs.
w.workspace.upload(f"{FOLDER}/ug_migration_toolkit.marker", io.BytesIO(b"Unity Gateway migration toolkit\n"),
                   format=ImportFormat.AUTO, overwrite=True)
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

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}` COMMENT 'Unity Gateway migration app results'")
print("schema ready:", RESULTS)

# COMMAND ----------

# MAGIC %md ## 3. Jobs

# COMMAND ----------

P = jobs.JobParameterDefinition


def job_settings(role: str, title: str, notebook: str, params: list, **extra) -> jobs.JobSettings:
    return jobs.JobSettings(
        name=f"{JOB_PREFIX} {title}", tags={**TAG, "app": APP_NAME, "role": role},
        parameters=params, max_concurrent_runs=1,
        tasks=[jobs.Task(task_key=role, notebook_task=jobs.NotebookTask(notebook_path=f"{FILES}/notebook/{notebook}"))],
        **extra)


SPECS = {
    "snapshot": job_settings("snapshot", "snapshot", "run_account", [
        P("days", "30"), P("snapshot_table", f"{RESULTS}.ug_migration"), P("out_dir", f"{FOLDER}/output/account"),
        P("deep_scan", "0"), P("deep_warehouse_id", WAREHOUSE_ID), P("requested_by", "schedule")],
        schedule=jobs.CronSchedule(quartz_cron_expression="0 0 6 ? * MON", timezone_id="UTC",
                                   pause_status=jobs.PauseStatus.PAUSED)),
    "scan": job_settings("scan", "workspace scan", "run_scan", [
        P("run_id", ""), P("job_run_id", "{{job.run_id}}"), P("results_schema", RESULTS), P("days", "30"),
        P("scan_roots", ""), P("target_catalog", "ai_gateway"), P("target_schema", "migrated"), P("requested_by", "")]),
    "apply": job_settings("apply", "apply", "run_apply", [
        P("apply_id", ""), P("job_run_id", "{{job.run_id}}"), P("results_schema", RESULTS), P("mode", "dry_run"),
        P("endpoints", ""), P("target_catalog", ""), P("target_schema", ""), P("uc_secret_map", ""),
        P("allow_secret_read", "false"), P("grants", "true"), P("rollback_of", ""), P("scan_run_id", ""),
        P("requested_by", "")]),
}
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

R = apps.AppResource
resources = [
    R(name="sql-warehouse", sql_warehouse=apps.AppResourceSqlWarehouse(
        id=WAREHOUSE_ID, permission=apps.AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE)),
    *[R(name=f"{role}-job", job=apps.AppResourceJob(id=str(JOB_IDS[role]),
                                                     permission=apps.AppResourceJobJobPermission.CAN_MANAGE_RUN))
      for role in ("snapshot", "scan", "apply")],
]
spec = apps.App(name=APP_NAME, resources=resources, user_api_scopes=["sql"],
                description="Unity Gateway Migration: account overview, workspace scans, readiness, code fixes and apply")
if get_app():
    w.apps.update(APP_NAME, spec)
    print("updated app", APP_NAME)
else:
    print("creating app (a few minutes)...")
    w.apps.create_and_wait(spec)
app = get_app()
if app.compute_status and app.compute_status.state and app.compute_status.state.value not in ("ACTIVE", "STARTING"):
    w.apps.start_and_wait(APP_NAME)

E = apps.EnvVar
deployment = apps.AppDeployment(
    source_code_path=f"{FILES}/app",
    command=["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
    env_vars=[E(name="DATABRICKS_WAREHOUSE_ID", value_from="sql-warehouse"),
              E(name="SNAPSHOT_JOB_ID", value_from="snapshot-job"), E(name="SCAN_JOB_ID", value_from="scan-job"),
              E(name="APPLY_JOB_ID", value_from="apply-job"), E(name="RESULTS_SCHEMA", value=RESULTS),
              E(name="SNAPSHOT_PREFIX", value="ug_migration"), E(name="OPERATORS", value=OPERATORS)])
print("deploying app...")
d = w.apps.deploy_and_wait(APP_NAME, deployment)
print("deployment:", d.status.state.value if d.status and d.status.state else d.status)

# COMMAND ----------

# MAGIC %md ## 5. Dashboard

# COMMAND ----------

dash_json = open(f"{FILES}/dashboard/ug_migration_progress.lvdash.json").read()
dash_id = find_dashboard_id()
if dash_id:
    dash = w.lakeview.update(dash_id, Dashboard(display_name=DASH_NAME, serialized_dashboard=dash_json,
                                                warehouse_id=WAREHOUSE_ID),
                             dataset_catalog=CATALOG, dataset_schema=SCHEMA)
else:
    dash = w.lakeview.create(Dashboard(display_name=DASH_NAME, serialized_dashboard=dash_json,
                                       warehouse_id=WAREHOUSE_ID, parent_path=FOLDER),
                             dataset_catalog=CATALOG, dataset_schema=SCHEMA)
print("dashboard ready (it fills in after the first snapshot)")

# COMMAND ----------

# MAGIC %md ## 6. Grants for app users
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
print("Dashboard:", f"{host}/sql/dashboardsv3/{dash.dashboard_id}")
for r, i in JOB_IDS.items():
    print(f"Job ({r}):", f"{host}/jobs/{i}")
displayHTML(f"""
<h3>Unity Gateway Migration is installed</h3>
<p><b>Open the app:</b> <a href="{app.url}" target="_blank">{app.url}</a></p>
<p>Dashboard: <a href="{host}/sql/dashboardsv3/{dash.dashboard_id}" target="_blank">Unity Gateway migration progress</a>
&nbsp;|&nbsp; Jobs: {", ".join(f'<a href="{host}/jobs/{i}" target="_blank">{r}</a>' for r, i in JOB_IDS.items())}</p>
<p>First steps in the app: <b>Overview</b> (Refresh account snapshot), then <b>Scans</b> (Start scan).
Operators: {OPERATORS or "(none)"}. Results: {RESULTS}. The user guide is in {FILES}/USER_GUIDE.md.</p>
<p>To let others view results, run (replace <code>migration-team</code> with your group):<br>
<code>GRANT USE CATALOG ON CATALOG `{CATALOG}` TO `migration-team`;<br>
GRANT USE SCHEMA, SELECT ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `migration-team`;</code></p>
""")

# COMMAND ----------

# Also return the links as the notebook result, so they're visible when the installer runs as a job.
dbutils.notebook.exit(json.dumps({"app": app.url, "dashboard": f"{host}/sql/dashboardsv3/{dash.dashboard_id}",
                                  "jobs": {r: f"{host}/jobs/{i}" for r, i in JOB_IDS.items()}}))
