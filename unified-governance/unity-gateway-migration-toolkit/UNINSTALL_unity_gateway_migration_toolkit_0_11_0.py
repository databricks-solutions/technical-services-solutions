# Databricks notebook source
# MAGIC %md
# MAGIC # Uninstall the Unity Gateway Migration Toolkit
# MAGIC
# MAGIC Removes a toolkit install from this workspace.
# MAGIC
# MAGIC 1. Leave **1. Action** at `preview` and click **Run all**. It lists what would be removed and kept, and changes nothing.
# MAGIC 2. Choose what else goes (widgets 3 to 5), set **1. Action** to `remove`, and click Run all again.
# MAGIC
# MAGIC Model services created by Apply stay unless you set **3** to `yes`. Schemas that hold services are never removed.
# MAGIC Uninstall refuses while a toolkit job is running.
# MAGIC
# MAGIC Prototype from Databricks Shared Technical Services, provided as is. Version 0.11.0.

# COMMAND ----------

# Widgets 1 to 4 (install) or 1 to 7 (uninstall). make_installer builds two notebooks from this template: INSTALL (MODE
# install) and UNINSTALL. Widget names start with a two-digit number: the panel sorts by name, so the number keeps them
# in order.
MODE = "uninstall"
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
CHOOSE_CATALOG, CHOOSE_WAREHOUSE = "<choose a catalog>", "<choose a warehouse>"
if MODE == "install":
    try:
        catalog_names = sorted({c.name for c in w.catalogs.list() if c.name})
    except Exception:  # can't list catalogs: the dropdown only offers the placeholder, and the install asks you to choose
        catalog_names = []
    warehouses = sorted(w.warehouses.list(), key=lambda x: (x.state is None or x.state.value != "RUNNING", x.name or ""))
    wh_labels = [f"{x.name} ({x.id})" for x in warehouses]
    if len(wh_labels) > 1:  # several warehouses: the user picks one (an update reuses the install's own)
        wh_choices, wh_default = [CHOOSE_WAREHOUSE] + wh_labels, CHOOSE_WAREHOUSE
    elif wh_labels:  # exactly one: preselected
        wh_choices, wh_default = wh_labels, wh_labels[0]
    else:
        wh_choices, wh_default = [CHOOSE_WAREHOUSE], CHOOSE_WAREHOUSE
    dbutils.widgets.dropdown("01_catalog", CHOOSE_CATALOG, [CHOOSE_CATALOG] + catalog_names,
                             "1. Catalog (the toolkit creates its schemas here)")
    dbutils.widgets.dropdown("02_warehouse", wh_default, wh_choices, "2. SQL warehouse")
    dbutils.widgets.text("03_target", "", "3. Schema for new model services (blank = <catalog>.ug_migrated, created for you)")
    dbutils.widgets.dropdown("04_setup", "quick", ["quick", "custom"],
                             "4. Setup (custom shows options 5 to 18; if they don't appear, click Run all)")
    # A fresh notebook in a workspace with no install yet: the first Run all only sets up the widgets (next cell). This
    # cell runs before the pip cell, on the runtime's own SDK, which can be too old for apps.list (0.20.0 on serverless,
    # seen live): so the REST API, directly.
    def _toolkit_app_here():
        token = None
        for _ in range(50):
            page = w.api_client.do("GET", "/api/2.0/apps", query={"page_size": 100, **({"page_token": token} if token else {})})
            if any((a.get("description") or "").startswith("Unity Gateway Migration Toolkit") for a in page.get("apps") or []):
                return True
            token = page.get("next_page_token")
            if not token:
                return False
        return True  # too many apps to tell: the checks decide

    try:
        _NO_INSTALL_HERE = not _toolkit_app_here()
    except Exception:  # noqa: BLE001 (can't tell: the checks decide)
        _NO_INSTALL_HERE = False
else:
    dbutils.widgets.dropdown("01_action", "preview", ["preview", "remove"], "1. Action (preview changes nothing)")
    dbutils.widgets.text("02_app_name", "", "2. App name (blank = the only install in this workspace)")
    dbutils.widgets.dropdown("03_rollback_services", "no", ["no", "yes"],
                             "3. Roll back services created by apply (yes = delete them too)")
    dbutils.widgets.dropdown("04_drop_data", "no", ["no", "yes"],
                             "4. Remove results tables (and the schema, if the toolkit made it and it's empty)")
    dbutils.widgets.dropdown("05_remove_logs", "no", ["no", "yes"],
                             "5. Remove apply logs (no = keep them, so kept services can be rolled back later)")
    dbutils.widgets.text("06_results_schema", "", "6. Results schema (catalog.schema; only if the run asks for it)")
    dbutils.widgets.dropdown("07_adopt_app", "no", ["no", "yes"],
                             "7. Also remove an app the installer didn't make (bundle or same name; only if the run asks for it)")

# COMMAND ----------

# Custom setup widgets (install only). This cell reads 4. Setup, so with the widget panel's default "On widget change:
# Run accessed commands", choosing custom reruns just this cell and widgets 5 to 18 appear. It makes no API calls (so
# it reruns in a moment) and defines everything it uses: it may rerun alone, after the pip cell restarted Python.
if "uninstall" == "install":
    _CUSTOM = ["05_app_name", "06_operators", "07_run_as", "08_create_target", "09_results_schema", "10_install_folder",
               "11_secret_schemas", "12_allow_secret_read", "13_deadline", "14_central_workspaces", "15_central_secret",
               "16_adopt_app", "17_allow_downgrade", "18_second_install"]

    def _widget_exists(name):
        try:
            dbutils.widgets.get(name)
            return True
        except Exception:  # noqa: BLE001 (a missing widget raises a runtime-specific error)
            return False

    if dbutils.widgets.get("04_setup") == "custom":
        _just_added = not any(_widget_exists(n) for n in _CUSTOM)
        T, D = dbutils.widgets.text, dbutils.widgets.dropdown
        T("05_app_name", "", "5. App name (blank = ug-migration-toolkit, or the install already here)")
        T("06_operators", "", "6. Operators who can start jobs in the app (emails, comma-separated; blank = you, or the current list)")
        T("07_run_as", "", "7. Run jobs as service principal (application ID; blank = you, or the current one; none = you)")
        D("08_create_target", "current", ["current", "yes", "no"],
          "8. Create the schema in 3 if it's missing (current = yes, or the install's choice; no = you create it, the SQL is printed)")
        T("09_results_schema", "", "9. Results schema name (blank = ug_migration, or the current one)")
        T("10_install_folder", "", "10. Install folder (blank = your home folder/ug-migration-toolkit, or the current one)")
        T("11_secret_schemas", "", "11. Allowed secret schemas (catalog.schema, comma-separated; blank = off, or the current list; none = off)")
        D("12_allow_secret_read", "current", ["current", "no", "yes"],
          "12. Allow reading secret values (risk: apply copies legacy secret values, in plain text, into the new services)")
        T("13_deadline", "", "13. Legacy deadline (YYYY-MM-DD; blank = 2027-03-30, or the current one)")
        T("14_central_workspaces", "", "14. Central mode: workspaces to manage (workspace IDs; blank = off, or the current list; none = off)")
        T("15_central_secret", "", "15. Central mode: OAuth secret of the service principal in 7 (scope/key; blank = the current one)")
        D("16_adopt_app", "no", ["no", "yes"], "16. Adopt an existing app with this name (yes overwrites it)")
        D("17_allow_downgrade", "no", ["no", "yes"], "17. Allow downgrade (an older version over a newer one)")
        D("18_second_install", "no", ["no", "yes"], "18. Allow a second install (needs its own app name, results schema and folder)")
        if _just_added:  # the new widgets have their defaults: let the user set them before anything runs
            dbutils.notebook.exit("Custom setup: widgets 5 to 18 are now in the widget panel. Set the ones you need "
                                  "(blank keeps the defaults or the current install's settings), then click Run all again.")
    else:
        for _name in _CUSTOM:
            if _widget_exists(_name):
                dbutils.widgets.remove(_name)
    # The first Run all of a freshly imported notebook: the widget panel was empty until now, so stop here instead of
    # failing later with "choose 1. Catalog". (An update needs no widgets: it reads the install already here.)
    if globals().get("_NO_INSTALL_HERE") and dbutils.widgets.get("01_catalog") == "<choose a catalog>":
        dbutils.notebook.exit("The widgets are ready at the top of the notebook. Pick 1. Catalog and 2. SQL warehouse "
                              "(and 3, if you want another schema for new model services), then click Run all again. "
                              "For more options, set 4. Setup to custom.")

# COMMAND ----------

# MAGIC %md Run all with 1. Action = preview first: it changes nothing

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk==0.158.0"
# MAGIC %restart_python

# COMMAND ----------

# HELPERS-BEGIN
# Pure helpers: no workspace calls. test_installer.py runs this block, so keep it free of dbutils, spark and w.
# (The widget cell runs before the pip restart, so the placeholder texts it uses are repeated here.)
import base64
import dataclasses
import io
import json
import re
import sys
import time
import uuid
import zipfile
from datetime import datetime, timedelta

from databricks.sdk.service import apps, jobs
from databricks.sdk.service.workspace import ImportFormat, Language

TOOL_TAG = "ug-migration-toolkit"
PROJECT_TAG = "unity-gateway-migration-toolkit"
APP_MARKER = "Unity Gateway Migration Toolkit"  # every toolkit app's description starts with this
LEGACY_MARKER = "Unity Gateway migration toolkit"  # the plain-text install marker of 0.7 and 0.8
DEFAULT_APP = "ug-migration-toolkit"  # app names are limited to 30 characters
LEGACY_APP = "unity-gateway-migration"  # the default app name in 0.8.0
BUNDLE_APP = "ug-migration-bundle"  # the bundle's default app name (databricks.yml)
CHOOSE_CATALOG = "<choose a catalog>"  # the widget placeholders: same text as in the widget cell
CHOOSE_WAREHOUSE = "<choose a warehouse>"
TARGET_SCHEMA_NAME = "ug_migrated"  # the default schema for new model services, in the catalog picked in 1
LEGACY_TARGET = "ai_gateway.migrated"  # the fixed default before 0.11.0; installs that used it keep it
CLEAR_WORDS = ("none", "off")  # typed in a custom widget, clears a setting the install already has
MARKER_NAME = "ug_migration_toolkit.marker"
TOOLKIT_NAMES = ("files", "output", "apply_logs", MARKER_NAME)  # what a toolkit folder holds
RESULT_TABLES = ("scans", "scan_items", "applies", "apply_items", "workspaces", "endpoints")
SYSTEM_TABLES = ("system.serving.endpoint_usage", "system.serving.served_entities", "system.ai_gateway.usage",
                 "system.access.workspaces_latest")  # read by the snapshot and the scans
NAME = r"[A-Za-z0-9_]+"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# App fields the API fills in. They are not sent back on update.
APP_OUTPUT_ONLY = {
    "active_deployment", "app_status", "compute_status", "create_time", "creator", "default_git_source",
    "default_source_code_path", "effective_budget_policy_id", "effective_usage_policy_id",
    "effective_user_api_scopes", "id", "oauth2_app_client_id", "oauth2_app_integration_id", "pending_deployment",
    "service_principal_client_id", "service_principal_id", "service_principal_name", "update_time", "updater", "url"}
SNAPSHOT_CRON = "0 0 6 ? * MON"
MAX_PASSES = 3  # rollback passes per uninstall
ROLLBACK_TIMEOUT = timedelta(minutes=60)


def split_list(raw: str) -> list[str]:
    return list(dict.fromkeys(x.strip() for x in (raw or "").split(",") if x.strip()))


def valid_app_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9-]{2,30}", name or ""))


def valid_folder(path: str) -> str | None:
    """Problem with an install folder, or None. It must be a subfolder below /Workspace/Users/<you>/ or
    /Workspace/Shared/: the home folder and the Shared root themselves are never used."""
    where = ("install folder must be a subfolder of /Workspace/Users/<you>/ or /Workspace/Shared/, for example "
             "/Workspace/Users/<you>/ug-migration-toolkit")
    parts = path.split("/")
    if len(parts) < 4 or parts[:2] != ["", "Workspace"] or parts[2] not in ("Users", "Shared"):
        return where
    if parts[2] == "Users" and len(parts) < 5:
        return where
    if any(s == "" or s.startswith(".") for s in parts[3:]):
        return "install folder can't contain empty parts, '.' or '..'"
    return None


def results_schema_for(raw: str, app_name: str) -> str:
    """Blank means ug_migration for the default app names (current and 0.8.0), else the app name with - as _."""
    raw = (raw or "").strip()
    if raw:
        return raw
    return "ug_migration" if app_name in (DEFAULT_APP, LEGACY_APP) else app_name.replace("-", "_")


def folder_for(raw: str, me: str, app_name: str) -> str:
    """Blank means a folder in your home folder named after the app, ending in -toolkit."""
    raw = (raw or "").strip().rstrip("/")
    return raw or f"/Workspace/Users/{me}/{app_name if app_name.endswith('-toolkit') else app_name + '-toolkit'}"


def is_service_principal(user_name: str) -> bool:
    return bool(re.fullmatch(UUID, user_name or ""))


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def downgrade_problem(prev: str, now: str, allow: bool) -> str | None:
    if prev and version_key(prev) > version_key(now) and not allow:
        return (f"this would downgrade the toolkit from {prev} to {now}: set 17. Allow downgrade (custom setup: 4. Setup = custom) = yes to do it anyway")
    return None


def parse_marker(text: str) -> dict:
    """The install marker is JSON since 0.8.1. The older marker is a plain line, so it has no version."""
    try:
        d = json.loads(text)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def marker_text(app_name: str, version: str, results: str, folder: str, who: str, target: str = "",
                create_target: bool = True, operators: list[str] | None = None) -> str:
    """The install marker. It also keeps what the API can't give back on an update: the Apps API returns an app's
    environment variable names without their values, so the operators are kept here."""
    return json.dumps({"app": app_name, "version": version, "results": results, "folder": folder,
                       "installed_by": who, "target": target, "create_target": create_target,
                       "operators": list(operators or [])}, indent=2) + "\n"


def marker_status(text: str | None, app_name: str) -> tuple[str, str]:
    """('missing' | 'ours' | 'other', the app the marker names). A plain-text marker names no app: its folder is ours."""
    if text is None:
        return "missing", ""
    d = parse_marker(text)
    if d:
        owner = str(d.get("app", ""))
        return ("ours" if owner == app_name else "other"), owner
    return ("ours" if text.startswith(LEGACY_MARKER) else "other"), ""


def is_toolkit_app(description: str | None) -> bool:
    return (description or "").startswith(APP_MARKER)


def app_from_job(name: str | None, tags: dict) -> str:
    """The app a toolkit job belongs to: its app tag. Jobs without one (bundle deploys) belong to no named install."""
    return (tags or {}).get("app") or ""


def bundle_made(job_name: str | None, app_name: str) -> bool:
    """True for a job the bundle deployed: installer jobs are named '[<app>] Unity Gateway migration ...'."""
    return not (job_name or "").startswith(f"[{app_name}] ")


def install_names(installs: list[dict], toolkit_apps: list[str]) -> list[str]:
    """App names to suggest: only valid names, from toolkit jobs and toolkit apps."""
    return sorted({i["app"] for i in installs if valid_app_name(i.get("app", ""))}
                  | {a for a in toolkit_apps if valid_app_name(a)})


def schema_made_by_toolkit(comment: str | None, app_name: str) -> bool:
    return f"(app: {app_name})" in (comment or "")


def parse_secret_schemas(raw: str) -> tuple[list[str], str | None]:
    schemas = split_list(raw)
    bad = [s for s in schemas if not re.fullmatch(rf"{NAME}\.{NAME}", s)]
    if bad:
        return schemas, "11. Allowed secret schemas (custom setup: 4. Setup = custom) must be catalog.schema, comma-separated: " + ", ".join(bad)
    return schemas, None


DEFAULT_DEADLINE = "2027-03-30"  # the legacy serving deadline for v1 and v2 (confirmed as of 2026-11-01)


def valid_deadline(text: str) -> str | None:
    """None when the legacy deadline is an ISO date (YYYY-MM-DD), else the problem to show."""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except (TypeError, ValueError):
        return f"13. Legacy deadline (custom setup: 4. Setup = custom) must be a date as YYYY-MM-DD (not {text!r})"
    return None


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


def valid_run_as(application_id: str) -> str | None:
    """Problem with 7. Run jobs as service principal (custom setup: 4. Setup = custom), or None. Blank is fine (the jobs run as the installer)."""
    if application_id and not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                                           application_id):
        return ("7. Run jobs as service principal (custom setup: 4. Setup = custom) must be the service principal's application ID (a UUID like "
                f"12345678-1234-1234-1234-123456789012), not {application_id!r}")
    return None


def central_problems(workspaces: str, secret_ref: str, run_as: str) -> tuple[list[str], list[str]]:
    """Central mode (optional): the allowlist and the problems with the two widgets. Blank workspaces = off.

    It scans other workspaces as the jobs' run-as service principal, so it needs that identity and a secret
    scope/key holding the service principal's OAuth secret (the value is only read by the scan job)."""
    ids, problems = [], []
    for part in (workspaces or "").split(","):
        p = part.strip()
        if not p:
            continue
        if not re.fullmatch(r"[0-9]{1,20}", p):
            problems.append(f"14. Central mode: workspaces (custom setup: 4. Setup = custom) takes workspace IDs (numbers), not {p!r}")
        elif p not in ids:
            ids.append(p)
    ref = (secret_ref or "").strip()
    if ids or ref:
        if not ids:
            problems.append("15. Central mode: OAuth secret (custom setup: 4. Setup = custom) is set, but no workspaces to manage")
        if not run_as:
            problems.append("central mode scans other workspaces as a service principal: set 7. Run jobs as "
                            "service principal to its application ID")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", ref):
            problems.append("15. Central mode: OAuth secret (custom setup: 4. Setup = custom) must be scope/key (the secret "
                            "holding that service principal's OAuth client secret)")
    return ids, problems


def job_settings(app_name: str, role: str, title: str, notebook_path: str, params: list, run_as: str = "",
                 **extra) -> jobs.JobSettings:
    if run_as:
        extra["run_as"] = jobs.JobRunAs(service_principal_name=run_as)
    return jobs.JobSettings(
        name=f"[{app_name}] Unity Gateway migration {title}",
        tags={"tool": TOOL_TAG, "Project": PROJECT_TAG, "app": app_name, "role": role},
        parameters=params, max_concurrent_runs=1,
        tasks=[jobs.Task(task_key=role, notebook_task=jobs.NotebookTask(notebook_path=notebook_path))],
        **extra)


def job_specs(app_name: str, folder: str, results: str, warehouse_id: str, secret_schemas: list[str],
              allow_secret_read: bool, deadline: str = DEFAULT_DEADLINE, run_as: str = "",
              central_workspaces: list[str] | None = None, central_secret: str = "",
              target: str = LEGACY_TARGET) -> dict[str, jobs.JobSettings]:
    """The three toolkit jobs. Parameter names match the notebooks in notebook/ and the bundle's databricks.yml.
    run_as: a service principal's application ID to run them as; blank runs them as the installing user.
    central_workspaces / central_secret: central mode (the scan and apply jobs may act on these other workspaces).
    target: catalog.schema for new model services (the scan's proposed names; the app prefills it in Apply)."""
    P = jobs.JobParameterDefinition
    target_catalog, target_schema = target.split(".", 1)
    central = [P("target_workspace_id", ""), P("central_workspaces", ",".join(central_workspaces or [])),
               P("central_client_id", run_as if central_workspaces else ""), P("central_secret", central_secret)]
    files = f"{folder}/files"
    return {
        "snapshot": job_settings(app_name, "snapshot", "snapshot", f"{files}/notebook/run_account", [
            P("days", "30"), P("snapshot_table", f"{results}.ug_migration"), P("out_dir", f"{folder}/output/account"),
            P("deep_scan", "0"), P("deep_wave", ""), P("deep_warehouse_id", warehouse_id), P("requested_by", "schedule"),
            P("deadline", deadline)], run_as=run_as,
            schedule=jobs.CronSchedule(quartz_cron_expression=SNAPSHOT_CRON, timezone_id="UTC",
                                       pause_status=jobs.PauseStatus.PAUSED)),
        "scan": job_settings(app_name, "scan", "workspace scan", f"{files}/notebook/run_scan", [
            P("run_id", ""), P("job_run_id", "{{job.run_id}}"), P("results_schema", results), P("days", "30"),
            P("scan_roots", ""), P("target_catalog", target_catalog), P("target_schema", target_schema),
            P("requested_by", ""), P("deadline", deadline),
            # Central mode: the allowlist, identity and secret are fixed here; the app only names the target.
            *central], run_as=run_as),
        "apply": job_settings(app_name, "apply", "apply", f"{files}/notebook/run_apply", [
            P("apply_id", ""), P("job_run_id", "{{job.run_id}}"), P("results_schema", results), P("mode", "dry_run"),
            P("endpoints", ""), P("target_catalog", ""), P("target_schema", ""), P("uc_secret_map", ""), P("create_uc_secrets", "false"),
            P("allow_secret_read", "false"), P("grants", "false"), P("rollback_of", ""), P("scan_run_id", ""),
            P("requested_by", ""), P("smoke_test", "false"), P("force", "false"), P("ack_guardrails", "false"),
            P("secret_schemas", ",".join(secret_schemas)),
            P("allow_secret_read_enabled", "true" if allow_secret_read else "false"),
            # Verify and cut over (operation other than apply); defaults match databricks.yml.
            P("operation", "apply"), P("api_type", ""), P("prompt", "Reply with: ok"), P("services", ""),
            P("dry_run_id", ""), *central], run_as=run_as),
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
            allow_secret_read: bool, deadline: str = DEFAULT_DEADLINE, central_workspaces: list[str] | None = None,
            hub_workspace_id: str = "", default_target: str = LEGACY_TARGET) -> list[apps.EnvVar]:
    E = apps.EnvVar
    return [
        E(name="UGMIG_CENTRAL_WORKSPACES", value=",".join(central_workspaces or [])),
        E(name="UGMIG_HUB_WORKSPACE_ID", value=hub_workspace_id),
        E(name="DATABRICKS_WAREHOUSE_ID", value_from="sql-warehouse"),
        E(name="SNAPSHOT_JOB_ID", value_from="snapshot-job"), E(name="SCAN_JOB_ID", value_from="scan-job"),
        E(name="APPLY_JOB_ID", value_from="apply-job"), E(name="RESULTS_SCHEMA", value=results),
        E(name="SNAPSHOT_PREFIX", value="ug_migration"), E(name="OPERATORS", value=",".join(operators)),
        E(name="UGMIG_VERSION", value=version), E(name="UGMIG_SECRET_SCHEMAS", value=",".join(secret_schemas)),
        E(name="UGMIG_ALLOW_SECRET_READ", value="true" if allow_secret_read else "false"),
        E(name="UGMIG_MAX_SCAN_AGE_DAYS", value="14"), E(name="UGMIG_DEADLINE", value=deadline),
        E(name="UGMIG_DEFAULT_TARGET", value=default_target)]


APP_UPDATE_MASK = "description,resources,user_api_scopes"  # what the installer owns on an existing app


def app_update_spec(existing: apps.App, **set_fields) -> apps.App:
    """The full App for apps.update (it replaces the app). Everything the API returned that the installer
    doesn't set (budget and usage policy, compute size, instances, space, git source...) is kept."""
    kept = {f.name: getattr(existing, f.name) for f in dataclasses.fields(apps.App) if f.name not in APP_OUTPUT_ONLY}
    kept.update(set_fields)
    return apps.App(**kept)


def rollback_command(folder: str, apply_id: str) -> str:
    return (f'python ug_migration_apply.py --profile <profile> rollback --log "{folder}/apply_logs/{apply_id}.jsonl"'
            " (a dry run; add --execute to roll back)")


def uninstall_plan(drop: bool, remove_logs: bool, rollback: bool, pending: list[dict], logs: set[str],
                   unmatched: list[dict], results: str, folder: str, marker_ok: bool) -> tuple[list, list, list, list]:
    """What an uninstall removes and keeps, what stops it, and warnings. pending: this install's apply runs with services
    still in place (apply_id, created); logs: apply ids with a log in <folder>/apply_logs; unmatched: other apply runs
    with services in the results schema. Returns (remove, keep, problems, warnings)."""
    created = sum(p.get("created", 0) for p in pending)
    ids = [p["apply_id"] for p in pending]
    remove, keep, problems, warnings = ["the app and its three jobs"], [], [], []
    if marker_ok:
        remove.append(f"the toolkit files, snapshot output and install marker in {folder}")
    else:
        keep.append(f"everything in {folder}: there is no toolkit marker for this app there, so nothing in that folder "
                    "is deleted (delete it by hand if it's yours to remove)")
    if pending and rollback:
        remove.insert(0, f"Unity Gateway services and grants created by {len(pending)} apply run(s) ({created} object(s)), "
                         "rolled back newest first before anything else is removed")
    elif pending:
        keep.append(f"Unity Gateway services created by {len(pending)} apply run(s) ({created} object(s)): callers that "
                    "moved to them keep working (to remove them, set 3. Roll back services = yes)")
        if remove_logs:
            problems.append("the apply logs are needed to roll back the kept services later: set 5. Remove apply "
                            "logs = no, or set 3. Roll back services = yes")
        missing = [a for a in ids if a not in logs]
        if drop and missing:
            problems.append(f"no apply log for apply run(s) {', '.join(missing)} in {folder}/apply_logs, so their services "
                            "couldn't be rolled back later: set 3. Roll back services = yes, or keep the results "
                            "tables (4. Remove results tables = no)")
        if drop:
            warnings.append(f"the results tables are removed while {len(ids)} apply run(s) keep their services. Roll them "
                            "back later from the command line: download the same toolkit zip, unzip it, and run:")
            warnings += ["  " + rollback_command(folder, a) for a in ids if a in logs]
        else:
            keep += ["roll back later: " + rollback_command(folder, a) for a in ids if a in logs]
    else:
        keep.append("no Unity Gateway services: no apply run has created any that is still in place")
    if drop and unmatched:
        problems.append(f"{len(unmatched)} apply run(s) in {results} with services in place aren't this install's (no apply "
                        "job run or log here): dropping the results tables would lose track of them. Keep the results "
                        "tables (4. Remove results tables = no)")
    if drop:
        remove.append(f"the results tables in {results} (ug_migration_*), and the schema if the toolkit made it and it's empty")
    else:
        keep.append(f"the results tables in {results}")
    if unmatched and not drop:
        keep.append(f"{len(unmatched)} apply run(s) in {results} that aren't this install's: left alone")
    if logs:
        (remove if remove_logs else keep).append(f"the apply logs in {folder}/apply_logs")
    return remove, keep, problems, warnings


def progress_decision(before: int, after: int, pass_no: int, max_passes: int) -> str:
    """After a rollback pass: 'done', 'again' (progress, and passes are left), 'stuck' (no progress) or 'limit'."""
    if after == 0:
        return "done"
    if after >= before:
        return "stuck"
    if pass_no >= max_passes:
        return "limit"
    return "again"


def system_table_fix(schemas: list[str], me: str) -> str:
    stmts = [f"GRANT USE CATALOG ON CATALOG system TO `{me}`;"]
    stmts += [f"GRANT USE SCHEMA, SELECT ON SCHEMA {s} TO `{me}`;" for s in schemas]
    return "ask an account admin to run: " + " ".join(stmts)


def create_schema_fix(catalog: str, owner: str, me: str) -> str:
    return (f"Ask the owner of catalog {catalog} ({owner}) to run: "
            f"GRANT USE CATALOG, CREATE SCHEMA ON CATALOG `{catalog}` TO `{me}`")


def target_schema_lines(target: str, who: str) -> list[str]:
    """The SQL that makes the schema for new model services ready for the apply job's identity."""
    c, sch = target.split(".", 1)
    return [f"CREATE SCHEMA IF NOT EXISTS `{c}`.`{sch}`;"] + target_grants(target, who)


def target_grants(target: str, who: str) -> list[str]:
    c, sch = target.split(".", 1)
    return [f"GRANT USE CATALOG ON CATALOG `{c}` TO `{who}`;",
            f"GRANT USE SCHEMA, CREATE SERVICE ON SCHEMA `{c}`.`{sch}` TO `{who}`;"]


def target_comment(app_name: str) -> str:
    return f"Unity Gateway model services created by the migration toolkit (app: {app_name})"


def parse_target(raw: str) -> tuple[str, str | None]:
    """(catalog.schema, problem). The widget takes catalog.schema; backticks and spaces are dropped."""
    t = (raw or "").replace("`", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", t):
        return t, (f"3. Schema for new model services must be catalog.schema (letters, digits, _ and -), not {t!r}; "
                   "leave it blank for <catalog>.ug_migrated")
    return t, None


def pick(widget: str, saved: str, default: str) -> str:
    """A setting: what the widget says, else what the install already uses, else the default. 'none' or 'off' clears
    it (back to the default), so an update never silently drops a setting, and dropping one is a choice."""
    v = (widget or "").strip()
    if v.lower() in CLEAR_WORDS:
        return default
    return v or (saved or "") or default


def app_name_for(raw: str, existing: list[str], uninstall: bool) -> tuple[str, str | None, str | None]:
    """(app name, note, problem). Blank: the default name if that install is here or nothing is, else the one toolkit
    install already in the workspace (so an update or uninstall needs no name). Several: the user must name one
    (uninstall always, even when one of them has the default name)."""
    raw = (raw or "").strip()
    if raw:
        return raw, None, None
    names = sorted(set(existing))
    if not names or (DEFAULT_APP in names and not (uninstall and len(names) > 1)):  # uninstall never guesses between installs
        return DEFAULT_APP, None, None
    if len(names) == 1:
        return names[0], f"found the install of app {names[0]} in this workspace: {'removing' if uninstall else 'updating'} it", None
    widget = "2. App name" if uninstall else "5. App name (custom setup: 4. Setup = custom)"
    return DEFAULT_APP, None, f"this workspace has several toolkit installs ({', '.join(names)}): set {widget} to one of them"


def saved_settings(jobs_of_app: list[dict], env: dict) -> dict:
    """What an existing install uses, read from its jobs (parameters and run-as) and its app's environment, so an
    update with blank widgets keeps it. jobs_of_app: [{"role", "params": {name: default}, "run_as"}]."""
    by = {j.get("role"): j for j in jobs_of_app}
    scan = (by.get("scan") or {}).get("params") or {}
    apply_ = (by.get("apply") or {}).get("params") or {}
    snap = (by.get("snapshot") or {}).get("params") or {}
    target = ".".join(x for x in (scan.get("target_catalog", ""), scan.get("target_schema", "")) if x)
    allow_read = apply_.get("allow_secret_read_enabled")
    return {
        "warehouse": snap.get("deep_warehouse_id", ""),
        "run_as": next((j.get("run_as") for j in jobs_of_app if j.get("run_as")), ""),
        "target": target if "." in target else "",
        "central_workspaces": scan.get("central_workspaces", ""),
        "central_secret": scan.get("central_secret", ""),
        "secret_schemas": apply_.get("secret_schemas", ""),
        "allow_secret_read": "" if allow_read is None else ("yes" if allow_read == "true" else "no"),
        "deadline": scan.get("deadline", ""),
        "operators": (env or {}).get("OPERATORS", ""),
    }


CHECK_MARK = {"ok": "OK  ", "fix": "FIX ", "note": "NOTE"}


def checklist_lines(checks: list[tuple[str, str, str]]) -> list[str]:
    """The checks as one list: OK, FIX (stops the install; nothing changes) and NOTE (doesn't stop it)."""
    lines = []
    for state, what, detail in checks:
        lines.append(f"  [{CHECK_MARK.get(state, state)}] {what}" + (f": {detail}" if detail else ""))
    return lines


def creates_lines(folder: str, results: str, target: str, target_state: str, app_name: str, run_as_label: str) -> list[str]:
    """What the install creates or updates, by name, so nothing it makes is a surprise."""
    tgt = {"exists": "already exists, kept as is", "created": "created for you",
           "missing": "not created (see the checklist)"}.get(target_state, target_state)
    return [f"  - Toolkit files: {folder}",
            f"  - Results schema (scan results and history): {results}",
            f"  - Schema for new model services (Apply creates services here, only when you run it): {target} ({tgt})",
            f"  - Jobs (run as {run_as_label}): [{app_name}] Unity Gateway migration snapshot, workspace scan, apply",
            f"  - App: {app_name} (Compute > Apps)"]


# What a rollback run's summary counts as problems (ug_migration_apply.PROBLEM_ACTIONS; a test checks they agree).
PROBLEM_ACTIONS = ("error", "manual", "mismatch", "kept", "needs_attention", "smoke_failed", "test_failed", "refused",
                   "missing", "protection_lost", "check_failed")


def rollback_done(status, summary) -> bool:
    """Whether a rollback run counts as rolled back: the app's rule (ug_migration_store.rollback_done; a test checks
    they agree). SUCCEEDED does. NEEDS_ATTENTION does when every object it kept was kept only because another apply
    run still uses it or it existed before the apply run, and nothing else needs attention: a run that reused a
    shared provider or secret keeps it on purpose and is rolled back. Before, only SUCCEEDED counted here, so such a
    run stayed pending and the uninstall stopped on it for good."""
    if status == "SUCCEEDED":
        return True
    if status != "NEEDS_ATTENTION":
        return False
    try:
        s = json.loads(summary or "{}") if not isinstance(summary, dict) else summary
    except (TypeError, ValueError):
        s = {}
    if not isinstance(s, dict):
        s = {}
    if "kept_other_run" not in s:  # written before this rule: NEEDS_ATTENTION counted as done
        return True
    if s.get("kept", 0) != s.get("kept_other_run", 0) + s.get("kept_preexisting", 0):
        return False
    return not any(s.get(a) for a in PROBLEM_ACTIONS if a != "kept")


# HELPERS-END

# COMMAND ----------

# The pip cell restarted Python, so the client and the signed-in user are created again here.
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
me_user = w.current_user.me()
me = me_user.user_name
MODE = "uninstall"


def widget(name: str, default: str = "") -> str:
    """A widget's value, or default when it isn't on the panel (quick setup has only 1 to 4)."""
    try:
        return dbutils.widgets.get(name)
    except Exception:  # noqa: BLE001 (a missing widget raises a runtime-specific error)
        return default


# Read the widgets only. The values are settled after the existing install is read (blank keeps what it uses).
UNINSTALL = MODE == "uninstall"
ACTION = ("uninstall: remove" if widget("01_action") == "remove" else "uninstall: preview") if UNINSTALL else "install"
PREVIEW = ACTION == "uninstall: preview"
CUSTOM_SETUP = not UNINSTALL and widget("04_setup") == "custom"
APP_RAW = widget("02_app_name" if UNINSTALL else "05_app_name")
if UNINSTALL:
    _given = widget("06_results_schema").replace("`", "").strip()
    if _given and "." not in _given:
        raise ValueError(f"Nothing was changed: 6. Results schema must be catalog.schema, not {_given!r}")
    CATALOG_PICKED, SCHEMA_RAW = (_given.split(".", 1) + [""])[:2] if "." in _given else ("", "")
else:
    CATALOG_PICKED, SCHEMA_RAW = widget("01_catalog").strip(), widget("09_results_schema")
CATALOG_GIVEN = CATALOG_PICKED not in ("", CHOOSE_CATALOG)
CATALOG = CATALOG_PICKED if CATALOG_GIVEN else ""
SCHEMA_GIVEN = bool(SCHEMA_RAW.strip())
_wh = re.search(r"\(([0-9a-f]+)\)$", widget("02_warehouse")) if not UNINSTALL else None
WAREHOUSE_GIVEN = _wh.group(1) if _wh else ""
TARGET_RAW = widget("03_target") if not UNINSTALL else ""
OPERATORS_RAW = widget("06_operators")
RUN_AS_RAW = widget("07_run_as")
CREATE_TARGET_RAW = widget("08_create_target")
FOLDER_RAW = widget("10_install_folder")
FOLDER_GIVEN = bool(FOLDER_RAW.strip())
SECRET_SCHEMAS_RAW = widget("11_secret_schemas")
ALLOW_SECRET_READ_RAW = widget("12_allow_secret_read", "current")
DEADLINE_RAW = widget("13_deadline")
CENTRAL_WORKSPACES_RAW = widget("14_central_workspaces")
CENTRAL_SECRET_RAW = widget("15_central_secret")
ADOPT = widget("07_adopt_app" if UNINSTALL else "16_adopt_app") == "yes"
ALLOW_DOWNGRADE = widget("17_allow_downgrade") == "yes"
SECOND_INSTALL = widget("18_second_install") == "yes"
DROP = widget("04_drop_data") == "yes"
REMOVE_LOGS = widget("05_remove_logs") == "yes"
ROLLBACK = widget("03_rollback_services") == "yes"
IS_SP = is_service_principal(me)
try:  # the same source the jobs and scans use (x-databricks-org-id): get_workspace_id() can differ on some workspaces
    import requests as _requests
    _org = _requests.get(f"{w.config.host.rstrip('/')}/api/2.0/clusters/spark-versions",
                         headers=w.config.authenticate(), timeout=30).headers.get("x-databricks-org-id")
    HUB_WORKSPACE_ID = str(_org or w.get_workspace_id())
except Exception:
    HUB_WORKSPACE_ID = ""
TOOLKIT_VERSION = "0.11.0"
APP_DESCRIPTION = f"{APP_MARKER}: account overview, workspace scans, readiness, code fixes and apply"

# COMMAND ----------

from databricks.sdk.errors import DatabricksError, NotFound, OperationFailed, PermissionDenied, ResourceDoesNotExist
from databricks.sdk.errors import NotImplemented as ApiNotImplemented  # HTTP 501; the builtin NotImplemented isn't an exception

DASH_NAME = "Unity Gateway migration progress"  # created by versions before 0.8.0; the app replaces it
RUNNING_STATES = ("PENDING", "QUEUED", "RUNNING", "STARTING", "TERMINATING")


def get_app():
    try:
        return w.apps.get(APP_NAME)
    except (NotFound, ResourceDoesNotExist):
        return None


def app_deleting(app) -> bool:
    return bool(app and app.compute_status and app.compute_status.state and app.compute_status.state.value == "DELETING")


def app_create_failed(app) -> bool:
    """An app whose create failed: compute in ERROR, no service principal and no deployment. It can't be updated
    ("has a fatal error ... delete the app and re-create it") and holds nothing to keep."""
    state = app.compute_status.state.value if app.compute_status and app.compute_status.state else ""
    return (state == "ERROR" and not getattr(app, "service_principal_client_id", None)
            and not getattr(app, "active_deployment", None))


def app_error(app) -> str:
    return (app.compute_status.message if app.compute_status and app.compute_status.message else "") or "unknown error"


def wait_app_gone(timeout_s: int = 900) -> None:
    """Waits until the app's name is free (after an uninstall the app can take a few minutes to go)."""
    deadline = time.time() + timeout_s
    while get_app() is not None:
        if time.time() > deadline:
            raise ValueError(f"app {APP_NAME} is still being deleted after {timeout_s // 60} minutes: wait a few minutes "
                             "(Compute > Apps), then run the installer again")
        time.sleep(10)


def exists(path: str) -> bool:
    try:
        w.workspace.get_status(path)
        return True
    except (NotFound, ResourceDoesNotExist):
        return False


def read_marker() -> str | None:
    try:
        # The marker is a workspace FILE: export(format=RAW) is refused for files, download() works.
        with w.workspace.download(MARKER) as f:
            return f.read().decode(errors="replace")
    except (NotFound, ResourceDoesNotExist):
        return None


def folder_children(path: str) -> list[str]:
    try:
        return [o.path.rsplit("/", 1)[-1] for o in w.workspace.list(path)]
    except (NotFound, ResourceDoesNotExist):
        return []


def find_dashboard_id() -> str | None:
    """The dashboard an earlier version of this installer created (the dashboards list API doesn't return paths)."""
    try:
        return w.workspace.get_status(f"{FOLDER}/{DASH_NAME}.lvdash.json").resource_id
    except (NotFound, ResourceDoesNotExist):
        return None


def toolkit_installs() -> list[dict]:
    """Every toolkit job in the workspace (matched on tags): app, role, job id, name, results schema and install folder.
    Jobs without an app tag (deployed by the bundle) get an empty app and aren't managed as a named install."""
    out = []
    for j in w.jobs.list(expand_tasks=True):
        s = j.settings
        tags = (s.tags or {}) if s else {}
        if tags.get("tool") != TOOL_TAG:
            continue
        # The list API returns no parameters and no run-as (seen live, 2026-11-11): read each toolkit job in full.
        try:
            s = w.jobs.get(j.job_id).settings or s
        except (NotFound, ResourceDoesNotExist):
            continue  # deleted since the list
        params = {p.name: p.default for p in (s.parameters or [])}
        results = params.get("results_schema") or params.get("snapshot_table", "").rsplit(".", 1)[0]
        path = s.tasks[0].notebook_task.notebook_path if s.tasks and s.tasks[0].notebook_task else ""
        run_as = s.run_as.service_principal_name if getattr(s, "run_as", None) else ""
        out.append({"job_id": j.job_id, "name": s.name or "", "app": app_from_job(s.name, tags),
                    "role": tags.get("role", ""), "results": results if "." in results else "",
                    "folder": install_folder_of(path), "params": params, "run_as": run_as or ""})
    return out


def toolkit_app_names() -> list[str]:
    return [a.name for a in w.apps.list() if is_toolkit_app(a.description)]


INSTALLS = toolkit_installs()  # read once; the checks and steps below use it
APP_NAME, _app_note, _app_problem = app_name_for(APP_RAW, install_names(INSTALLS, toolkit_app_names()), UNINSTALL)
if _app_note:
    print(_app_note)
if _app_problem:
    raise ValueError("Nothing was changed: " + _app_problem)
if not valid_app_name(APP_NAME):
    raise ValueError(f"Nothing was changed: the app name must be 2-30 lowercase letters, digits or hyphens (not {APP_NAME!r})")
MINE = [i for i in INSTALLS if i["app"] == APP_NAME]
EXISTING_APP = get_app()
SAVED = saved_settings(MINE, {e.name: e.value for e in (EXISTING_APP.active_deployment.env_vars or [])}
                       if EXISTING_APP and EXISTING_APP.active_deployment else {})
SCHEMA = results_schema_for(SCHEMA_RAW, APP_NAME)
RESULTS = f"{CATALOG}.{SCHEMA}"
FOLDER = folder_for(FOLDER_RAW, me, APP_NAME)
FILES = f"{FOLDER}/files"
MARKER = f"{FOLDER}/{MARKER_NAME}"


def adopt_existing_locations() -> None:
    """Blank widgets keep the locations this app was installed with (earlier versions used other defaults), so an
    update doesn't split the install. A widget with a value must agree with the existing install, or the run stops."""
    global CATALOG, SCHEMA, RESULTS, FOLDER, FILES, MARKER
    results = next((i["results"] for i in MINE if i["results"]), "")
    folder = next((i["folder"] for i in MINE if i["folder"]), "")
    if results:
        rc, rs = results.split(".", 1)
        if not SCHEMA_GIVEN and CATALOG_GIVEN and CATALOG != rc:
            raise ValueError(f"{'6. Results schema' if UNINSTALL else '1. Catalog'} is {CATALOG}, but app {APP_NAME} already keeps its results in "
                             f"{results}. Pick catalog {rc} to update it, or choose another App name for a second install "
                             "(18. Allow a second install (custom setup: 4. Setup = custom) = yes)")
        if not SCHEMA_GIVEN:
            CATALOG, SCHEMA = rc, rs
            print("using the results schema of the existing install:", results)
        elif not CATALOG_GIVEN:
            CATALOG = rc
    RESULTS = f"{CATALOG}.{SCHEMA}"
    if results and RESULTS != results:
        raise ValueError(f"app {APP_NAME} is installed with its results in {results}, not {RESULTS}: leave 9. Results "
                         "schema blank and pick that catalog to update it, or choose another App name for a second install")
    if folder:
        if not FOLDER_GIVEN:
            FOLDER = folder
            print("using the install folder of the existing install:", FOLDER)
        elif FOLDER != folder:
            raise ValueError(f"app {APP_NAME} is installed in {folder}, not {FOLDER}: leave 10. Install folder (custom setup: 4. Setup = custom) blank "
                             "to update it, or choose another App name for a second install")
    FILES = f"{FOLDER}/files"
    MARKER = f"{FOLDER}/{MARKER_NAME}"


adopt_existing_locations()
if UNINSTALL and not MINE and not EXISTING_APP and not exists(MARKER):
    found = install_names(INSTALLS, toolkit_app_names())
    unnamed = [j["name"] for j in INSTALLS if not j["app"]]
    raise ValueError(f"no install named {APP_NAME}; found: {', '.join(found) or 'no toolkit installs in this workspace'}"
                     + (f". Also {len(unnamed)} toolkit job(s) deployed by the bundle without an app name (not managed "
                        "here): " + ", ".join(unnamed) if unnamed else ""))
if UNINSTALL and not CATALOG:
    raise ValueError("set 6. Results schema (catalog.schema): this install's results schema isn't recorded in its jobs")
MARKER_KIND, MARKER_APP = marker_status(read_marker(), APP_NAME)
SAVED_MARKER = parse_marker(read_marker() or "") if MARKER_KIND == "ours" else {}

# Settle every setting: the widget, else what this install already uses, else the default. Quick setup leaves the
# custom widgets off the panel, so an update keeps the install's settings without asking for them again.
WAREHOUSE_ID = WAREHOUSE_GIVEN or SAVED["warehouse"]
SAVED_OPERATORS = ",".join(SAVED_MARKER.get("operators") or []) or SAVED["operators"]
OPERATOR_LIST = split_list(pick(OPERATORS_RAW, SAVED_OPERATORS, ""))
if not OPERATOR_LIST and not IS_SP:
    OPERATOR_LIST = [me]  # people: the signed-in user by default. Service principals must set it.
# An install from before 0.11.0 has no operators in its marker, and the Apps API doesn't return them: say so.
# Only an app that was deployed has operators to lose (a first create that failed has none).
OPERATORS_UNKNOWN = bool(EXISTING_APP and EXISTING_APP.active_deployment and not OPERATORS_RAW.strip()
                         and not SAVED_OPERATORS and not UNINSTALL)
RUN_AS = pick(RUN_AS_RAW, SAVED["run_as"], "")
run_as_problem = valid_run_as(RUN_AS)
TARGET, target_problem = parse_target(pick(TARGET_RAW, SAVED["target"] or SAVED_MARKER.get("target", ""),
                                           f"{CATALOG}.{TARGET_SCHEMA_NAME}" if CATALOG else LEGACY_TARGET))
CREATE_TARGET = pick("" if CREATE_TARGET_RAW == "current" else CREATE_TARGET_RAW,
                     {True: "yes", False: "no"}.get(SAVED_MARKER.get("create_target"), ""), "yes") == "yes"
SECRET_SCHEMAS, secret_problem = parse_secret_schemas(pick(SECRET_SCHEMAS_RAW, SAVED["secret_schemas"], ""))
ALLOW_SECRET_READ = (ALLOW_SECRET_READ_RAW if ALLOW_SECRET_READ_RAW in ("yes", "no") else SAVED["allow_secret_read"]) == "yes"
DEADLINE = pick(DEADLINE_RAW, SAVED["deadline"], DEFAULT_DEADLINE)
deadline_problem = valid_deadline(DEADLINE)
_central_off = CENTRAL_WORKSPACES_RAW.strip().lower() in CLEAR_WORDS  # turning central mode off drops its secret too
CENTRAL_WORKSPACES, central_problem_list = central_problems(
    pick(CENTRAL_WORKSPACES_RAW, SAVED["central_workspaces"], ""),
    "" if _central_off else pick(CENTRAL_SECRET_RAW, SAVED["central_secret"], ""), RUN_AS)
CENTRAL_SECRET = pick(CENTRAL_SECRET_RAW, SAVED["central_secret"], "") if CENTRAL_WORKSPACES else ""
JOB_IDENTITY = f"service principal {RUN_AS}" if RUN_AS else me
kept = [label for label, raw, saved in (
    ("operators", OPERATORS_RAW, SAVED_OPERATORS), ("run-as service principal", RUN_AS_RAW, SAVED["run_as"]),
    ("schema for new model services", TARGET_RAW, SAVED["target"]), ("SQL warehouse", WAREHOUSE_GIVEN, SAVED["warehouse"]),
    ("secret schemas", SECRET_SCHEMAS_RAW, SAVED["secret_schemas"]), ("deadline", DEADLINE_RAW, SAVED["deadline"]),
    ("central mode", CENTRAL_WORKSPACES_RAW, SAVED["central_workspaces"])) if not raw.strip() and saved]
if kept and not UNINSTALL:
    print("kept from the existing install: " + ", ".join(kept) + " (custom setup changes them; 'none' clears one)")

problems = []
if CATALOG_GIVEN and not re.fullmatch(NAME, CATALOG):
    problems.append("1. Catalog must use letters, digits and underscores")
if not re.fullmatch(NAME, SCHEMA):
    problems.append("9. Results schema (custom setup: 4. Setup = custom) must use letters, digits and underscores")
if valid_folder(FOLDER):
    problems.append(valid_folder(FOLDER) + f" (10. Install folder (custom setup: 4. Setup = custom) is {FOLDER!r})")
for _p in (secret_problem, deadline_problem, run_as_problem):
    if _p:
        problems.append(_p)
problems += central_problem_list
if not UNINSTALL:
    if target_problem:
        problems.append(target_problem)
    if not CATALOG:
        problems.append("choose 1. Catalog (the toolkit creates its schemas there; you need USE CATALOG and "
                        "CREATE SCHEMA on it)")
    if not WAREHOUSE_ID:
        problems.append("choose 2. SQL warehouse (none found: ask a workspace admin to create one or give you CAN USE "
                        "on one)")
    if IS_SP and not split_list(pick(OPERATORS_RAW, SAVED_OPERATORS, "")):
        problems.append("this runs as a service principal, so set 6. Operators (custom setup: 4. Setup = custom) to the emails of the people "
                        "who can start jobs in the app")
if problems:
    raise ValueError("Nothing was changed. Fix the widgets first: " + "; ".join(problems))
print(f"{ACTION}: app {APP_NAME}, results {RESULTS}, folder {FOLDER}" + ("" if UNINSTALL else
      f", schema for new model services {TARGET}, operators {', '.join(OPERATOR_LIST) or '(none)'}, jobs run as {JOB_IDENTITY}"))


def run_sql(statement: str) -> str | None:
    """None if the statement succeeds on the chosen warehouse, else the error text."""
    r = w.statement_execution.execute_statement(statement=statement, warehouse_id=WAREHOUSE_ID, wait_timeout="50s")
    if r.status and r.status.state and r.status.state.value == "SUCCEEDED":
        return None
    if r.status and r.status.error:
        return r.status.error.message
    return f"state {r.status.state.value if r.status and r.status.state else 'unknown'}"


WAREHOUSE_NAME = ""


def start_warehouse() -> str | None:
    """Starts the SQL warehouse if it's stopped and waits until it runs. Returns a problem, or None."""
    global WAREHOUSE_NAME
    try:
        wh = w.warehouses.get(WAREHOUSE_ID)
    except (NotFound, ResourceDoesNotExist):
        return "the SQL warehouse wasn't found: pick one in 2. SQL warehouse"
    WAREHOUSE_NAME = f"{wh.name} ({WAREHOUSE_ID})" if wh.name else WAREHOUSE_ID
    state = wh.state.value if wh.state else "UNKNOWN"
    if state != "RUNNING":
        print(f"starting SQL warehouse {wh.name or WAREHOUSE_ID} (it is {state}); this can take a few minutes...")
        try:
            w.warehouses.start_and_wait(WAREHOUSE_ID, timeout=timedelta(minutes=15))
        except Exception as e:  # reported below, with the state it ended in
            print("  the start didn't finish:", str(e)[:200])
        wh = w.warehouses.get(WAREHOUSE_ID)
        state = wh.state.value if wh.state else "UNKNOWN"
    if state != "RUNNING":
        return (f"the SQL warehouse {wh.name or WAREHOUSE_ID} is {state}, not RUNNING: start it in SQL Warehouses (or pick "
                "another one in 2. SQL warehouse), then run the installer again")
    return None


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


RUN_AS_ROLE_FIX = ("in this workspace, open Settings > Identity and access > Service principals > {sp} > Permissions and "
                   "give yourself (or a group you're in) the Service principal: User role, then run the installer again")


def run_as_user_problem(application_id: str) -> str | None:
    """Jobs can only run as a service principal if the person creating them holds its Service principal: User role
    (Manager isn't enough, and neither is workspace admin). Best effort: None when it holds, or when it can't be read."""
    if not application_id:
        return None
    try:
        rows = spark.sql("SELECT account_id FROM system.access.workspaces_latest WHERE workspace_id = "
                         f"{int(w.get_workspace_id())} LIMIT 1").collect()
        if not rows:
            return None
        name = f"accounts/{rows[0][0]}/servicePrincipals/{application_id}/ruleSets/default"
        rules = w.api_client.do("GET", "/api/2.0/preview/accounts/access-control/rule-sets",
                                query={"name": name, "etag": ""}).get("grant_rules") or []
    except Exception:  # can't tell: the job step reports it if it's missing
        return None
    mine = {f"users/{me}", f"servicePrincipals/{me}"} | {f"groups/{gr.display}" for gr in (me_user.groups or [])
                                                         if gr.display}
    if any(r.get("role") == "roles/servicePrincipal.user" and mine & set(r.get("principals") or []) for r in rules):
        return None
    return (f"the jobs run as service principal {application_id}, and creating them needs its Service principal: User "
            "role, which you don't have (Manager isn't enough): " + RUN_AS_ROLE_FIX.format(sp=application_id))


def installed_version(existing) -> str:
    """The version of the install in the folder (marker), else the version the existing app was deployed with."""
    marker = parse_marker(read_marker() or "")
    if marker.get("version"):
        return marker["version"]
    if existing and existing.active_deployment and existing.active_deployment.env_vars:
        env = {e.name: e.value for e in existing.active_deployment.env_vars}
        return env.get("UGMIG_VERSION", "")
    return ""


def active_job_names() -> list[str]:
    """Names of this install's jobs (all three roles) that have a run in progress."""
    return [j["name"] for j in MINE if next(iter(w.jobs.list_runs(job_id=j["job_id"], active_only=True)), None)]


CHECKS: list[tuple[str, str, str]] = []  # (ok | fix | note, what, detail): printed as one checklist
TARGET_STATE = {"state": "missing"}  # exists | created | missing: the schema for new model services


def passed(what: str, detail: str = "") -> None:
    CHECKS.append(("ok", what, detail))


def sql_lines(who: str) -> str:
    return "\n      ".join(target_schema_lines(TARGET, who))


def target_check(create_now: bool) -> tuple[str, str, str]:
    """(check state, schema state, detail) for the schema for new model services. Never stops the install: scans
    don't need it, and Apply waits (with the SQL) until it exists. With create_now, a missing schema is created here,
    as the last check (the step would create it anyway), like the results schema."""
    who = RUN_AS or me
    cat = TARGET.split(".", 1)[0]
    try:
        w.schemas.get(TARGET)
        return "ok", "exists", (f"{TARGET} exists. The apply job ({JOB_IDENTITY}) needs USE CATALOG, USE SCHEMA and "
                                "CREATE SERVICE on it")
    except (NotFound, ResourceDoesNotExist):
        pass
    except DatabricksError as e:  # it may exist, but you can't see it: never a reason to stop the install
        return "note", "missing", (f"couldn't check {TARGET} ({str(e)[:120]}). If it exists, the apply job ({JOB_IDENTITY}) "
                                   f"needs USE CATALOG, USE SCHEMA and CREATE SERVICE on it; if not, create it:\n      {sql_lines(who)}")
    sql = sql_lines(who)
    if not CREATE_TARGET:
        return "note", "missing", (f"{TARGET} doesn't exist, and 8. Create the schema = no. Create it before you use "
                                   f"Apply (scans work without it):\n      {sql}")
    try:
        cat_info = w.catalogs.get(cat)
    except DatabricksError:
        return "note", "missing", (f"catalog {cat} doesn't exist or you can't see it, so {TARGET} can't be created. Set "
                                   "3. Schema for new model services to a schema in a catalog you can use (blank = "
                                   f"<catalog>.{TARGET_SCHEMA_NAME}), or create it. Scans work without it; Apply waits")
    if not create_now:
        return "ok", "missing", f"{TARGET} doesn't exist: it will be created"
    err = run_sql(f"CREATE SCHEMA IF NOT EXISTS `{cat}`.`{TARGET.split('.', 1)[1]}` COMMENT '{target_comment(APP_NAME)}'")
    if err:
        return "note", "missing", (f"couldn't create {TARGET} ({err[:160]}). {create_schema_fix(cat, cat_info.owner, me)}, "
                                   f"or ask an admin to run:\n      {sql}\n    Or set 3. Schema for new model services to a "
                                   "schema you have. Scans work without it; Apply waits until it exists")
    return "ok", "created", f"created {TARGET}"


def preflight() -> tuple[list[str], list[str], str]:
    """Checks before anything is created, changed or deleted. Returns (problems, notes, version note), and fills
    CHECKS. The only writes: the SQL warehouse is started if stopped, and the results schema and the schema for new
    model services are created as the last checks, when missing and everything else passed (the steps would anyway)."""
    found, notes = [], []
    try:
        next(iter(w.apps.list(page_size=1)), None)
    except DatabricksError as e:
        return [f"Databricks Apps isn't usable here ({str(e)[:200]}): ask a workspace admin to enable Apps for you, or to "
                "let you create apps"], notes, ""
    passed("Databricks Apps", "you can create apps")
    if OPERATORS_UNKNOWN:  # once, for installs before 0.11.0: never shrink or grow who can start jobs silently
        found.append("the operators of this install (who can start jobs in the app) can't be read back: Databricks "
                     "doesn't return an app's settings, and installs before 0.11.0 didn't record them. Set 4. Setup to "
                     "custom, click Run all, enter them in 6. Operators (your email alone is fine), then Run all again. "
                     "From then on, updates keep them")
    unnamed = [j["name"] for j in INSTALLS if not j["app"]]
    if unnamed:
        notes.append(f"{len(unnamed)} toolkit job(s) deployed by the bundle have no app name and aren't managed by this "
                     "installer (left alone): " + ", ".join(unnamed))
    if EXISTING_APP and not is_toolkit_app(EXISTING_APP.description) and not ADOPT:
        found.append(f"an app named {APP_NAME} exists and isn't a toolkit app: " + (
            "choose another App name, or set 16. Adopt existing app (custom setup: 4. Setup = custom) = yes if it can be replaced" if not UNINSTALL
            else "uninstall won't delete it (set 7. Also remove an app the installer didn't make = yes to delete it anyway)"))
    bundle_jobs = [j["name"] for j in MINE if bundle_made(j["name"], APP_NAME)]
    if (bundle_jobs or (EXISTING_APP and APP_NAME == BUNDLE_APP)) and not ADOPT:
        found.append(f"the app {APP_NAME} and its jobs were deployed by the bundle (databricks bundle deploy), not by this "
                     "installer: " + ("set 16. Adopt existing app (custom setup: 4. Setup = custom) = yes to take them over, or choose another App name"
                                      if not UNINSTALL else "set 7. Also remove an app the installer didn't make = yes to remove them here, "
                                      "or remove them with the bundle (databricks bundle destroy)"))
    # Other installs, by app name (jobs and apps), and what they share with this one.
    others = [{"app": i["app"], "results": i["results"], "folder": i["folder"]}
              for i in INSTALLS if valid_app_name(i["app"]) and i["app"] != APP_NAME]
    for a in w.apps.list():
        if a.name != APP_NAME and is_toolkit_app(a.description):
            env = {e.name: e.value for e in (a.active_deployment.env_vars or [])} if a.active_deployment else {}
            others.append({"app": a.name, "results": env.get("RESULTS_SCHEMA", ""), "folder": ""})
    foreign = sorted({o["app"] for o in others})
    clash = shared_state(others, RESULTS, FOLDER)
    if UNINSTALL:
        if clash and any(c["kind"] == "folder" for c in clash):
            found.append("uninstall would delete files that another install uses in the same folder: "
                         + ", ".join(c["app"] for c in clash if c["kind"] == "folder"))
        if (DROP or ROLLBACK) and any(c["kind"] == "results" for c in clash):
            found.append(f"the results schema {RESULTS} is shared with the toolkit install of app "
                         + ", ".join(c["app"] for c in clash if c["kind"] == "results")
                         + ": uninstall can't roll back or drop it (leave both Uninstall results options at no)")
    else:
        # Only a new install needs the flag: updating one that is already here never adds a second install (the
        # shared-location checks below still apply).
        if foreign and not SECOND_INSTALL and not (MINE or EXISTING_APP):
            found.append("another toolkit install exists under app name " + ", ".join(foreign) + ": set 5. App name (custom setup: 4. Setup = custom) "
                         "to that name to update it, or uninstall it first (to run two side by side, set 18. Allow a "
                         "second install = yes, with other results schema and install folder)")
        for c in clash:
            label = "results schema" if c["kind"] == "results" else "install folder"
            found.append(f"the {label} {RESULTS if c['kind'] == 'results' else FOLDER} is used by the toolkit install of app "
                         f"{c['app']}: choose another {label} (custom setup: 4. Setup = custom)")
    for name in active_job_names():
        found.append(f"the job '{name}' has a run in progress: wait for it to finish in Jobs, then run again")
    if not found:
        passed("Other installs and running jobs", "nothing in the way")
    if not UNINSTALL:
        if MARKER_KIND == "other":
            found.append(f"the install folder {FOLDER} belongs to another toolkit install (marker app {MARKER_APP or '?'}): "
                         "choose another 10. Install folder (custom setup: 4. Setup = custom)")
        elif MARKER_KIND == "missing" and any(c not in TOOLKIT_NAMES for c in folder_children(FOLDER)):
            found.append(f"the install folder {FOLDER} has files that aren't the toolkit's and no toolkit marker, so the "
                         "installer won't touch them: choose an empty folder (10. Install folder (custom setup: 4. Setup = custom))")
        try:
            cat = w.catalogs.get(CATALOG)
        except DatabricksError as e:  # missing, or no USE CATALOG (PermissionDenied)
            cat = None
            found.append(f"results catalog {CATALOG!r} doesn't exist or you can't use it ({str(e)[:120]}): pick another "
                         "in 1. Catalog, or ask its owner for USE CATALOG and CREATE SCHEMA")
        schema = None
        if cat is not None:
            passed("Catalog", f"{CATALOG} (the results schema goes here)")
            try:
                schema = w.schemas.get(RESULTS)
            except (NotFound, ResourceDoesNotExist):
                schema = None
            except DatabricksError as e:  # it exists, but you can't read it
                schema = None
                found.append(f"you can't read the results schema {RESULTS} ({str(e)[:120]}): ask its owner for USE SCHEMA, "
                             "CREATE TABLE and MODIFY, or choose another results schema (9. Results schema (custom setup: 4. Setup = custom))")
            if schema:
                owner_app = re.search(r"\(app: ([a-z0-9_-]+)\)", schema.comment or "")
                if owner_app and owner_app.group(1) != APP_NAME:
                    found.append(f"results schema {RESULTS} belongs to app {owner_app.group(1)}: choose another results schema "
                                 "(9. Results schema (custom setup: 4. Setup = custom))")
                elif schema.owner != me and not can_use("schema", RESULTS, {"ALL_PRIVILEGES", "CREATE_TABLE", "MODIFY"}):
                    found.append(f"you can't write to {RESULTS}: ask the owner of the schema ({schema.owner}) to run: GRANT "
                                 f"USE SCHEMA, CREATE TABLE, MODIFY ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `{me}`")
                else:
                    passed("Results schema", f"{RESULTS} exists and you can write to it")
        wh_problem = start_warehouse()
        if wh_problem:
            found.append(wh_problem)
        else:
            passed("SQL warehouse", f"{WAREHOUSE_NAME or WAREHOUSE_ID} is running")
            missing: dict[str, list[str]] = {}
            for t in SYSTEM_TABLES:
                err = run_sql(f"SELECT 1 FROM {t} LIMIT 1")
                if err:
                    missing.setdefault(t.rsplit(".", 1)[0], []).append((t, err[:160]))
            for schema_name, tables in missing.items():
                found.append(f"the SQL warehouse can't read {', '.join(t for t, _ in tables)} (the snapshot and scans "
                             "need SELECT on it). " + system_table_fix([schema_name], me)[0].upper()
                             + system_table_fix([schema_name], me)[1:] + ". Error: " + "; ".join(e for _, e in tables))
            if not missing:
                passed("System tables", "the warehouse can read the four the snapshot and scans use")
        role_problem = run_as_user_problem(RUN_AS)
        if role_problem:
            found.append(role_problem)
        elif RUN_AS:
            passed("Run-as service principal", f"you can run jobs as {RUN_AS}")
        prev = installed_version(EXISTING_APP)
        note = f"version: {prev} -> {TOOLKIT_VERSION}" if prev else f"version: new install of {TOOLKIT_VERSION}"
        problem = downgrade_problem(prev, TOOLKIT_VERSION, ALLOW_DOWNGRADE)
        if problem:
            found.append(problem)
        else:
            passed("Version", f"update {prev} -> {TOOLKIT_VERSION}" if prev else f"new install of {TOOLKIT_VERSION}")
        if not found and cat is not None and schema is None:  # the probe: create the schema as the last check
            err = run_sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}` COMMENT 'Unity Gateway migration app results "
                          f"(app: {APP_NAME})'")
            if err:
                found.append(f"you can't create {RESULTS} ({err[:200]}). " + create_schema_fix(CATALOG, cat.owner, me))
            else:
                passed("Results schema", f"created {RESULTS}")
        state, TARGET_STATE["state"], detail = target_check(create_now=not found)
        CHECKS.append((state, "Schema for new model services", detail))
        return found, notes, note
    return found, notes, "uninstall"


PROBLEMS, NOTES, VERSION_NOTE = preflight()
for n in NOTES:
    print("Note:", n)

# COMMAND ----------

def apply_job_ids() -> list[int]:
    return [i["job_id"] for i in MINE if i["role"] == "apply"]


def pending_rows() -> list[dict]:
    """Execute runs in the results schema whose services are still in place (no finished rollback), newest first."""
    try:
        rows = spark.sql(f"""
            SELECT a.apply_id, a.job_run_id, count(i.payload) AS created FROM `{CATALOG}`.`{SCHEMA}`.ug_migration_applies a
            LEFT JOIN `{CATALOG}`.`{SCHEMA}`.ug_migration_apply_items i
              ON i.apply_id = a.apply_id AND get_json_object(i.payload, '$.action') = 'created'
            WHERE a.mode = 'execute'
            GROUP BY a.apply_id, a.job_run_id, a.started_at ORDER BY a.started_at DESC""").collect()
        rolled = spark.sql(f"""
            SELECT rollback_of, status, summary FROM `{CATALOG}`.`{SCHEMA}`.ug_migration_applies
            WHERE mode = 'rollback' AND rollback_of IS NOT NULL""").collect()
    except Exception as e:  # no results tables yet: nothing was applied from this install
        if "TABLE_OR_VIEW_NOT_FOUND" in str(e) or "SCHEMA_NOT_FOUND" in str(e):
            return []
        raise
    done = {r["rollback_of"] for r in rolled if rollback_done(r["status"], r["summary"])}
    return [{"apply_id": r["apply_id"], "job_run_id": str(r["job_run_id"] or ""), "created": r["created"]}
            for r in rows if r["created"] and r["apply_id"] not in done]


def log_apply_ids() -> set[str]:
    """Apply ids with a log in this install's apply_logs folder (one <apply_id>.jsonl per execute run)."""
    return {n[: -len(".jsonl")] for n in folder_children(f"{FOLDER}/apply_logs") if re.fullmatch(UUID + r"\.jsonl", n)}


def apply_state() -> dict:
    """This install's apply runs that still have services in place (pending, newest first). A run is this install's when
    its job run is one of this app's apply job runs, or its log is in this install's apply_logs folder."""
    run_ids = {str(r.run_id) for job_id in apply_job_ids() for r in w.jobs.list_runs(job_id=job_id)}
    logs = log_apply_ids()
    rows = pending_rows()
    pending = [r for r in rows if r["job_run_id"] in run_ids or r["apply_id"] in logs]
    mine_ids = {r["apply_id"] for r in pending}
    return {"pending": pending, "unmatched": [r for r in rows if r["apply_id"] not in mine_ids], "logs": logs}


def run_status(run_id: str) -> str:
    """Status of one apply-job run in the results table, by the apply_id the installer gave it."""
    rows = spark.sql(f"SELECT status FROM `{CATALOG}`.`{SCHEMA}`.ug_migration_applies WHERE apply_id = :id",
                     args={"id": run_id}).collect()
    return rows[0]["status"] if rows else "not recorded"


def run_apply_job(job_id: int, params: dict) -> str | None:
    """Start the apply job and wait for it. Returns 'still running' on a timeout, else None: a failed run is not an
    error here, because its row in the apply table says how far it got (or that the job refused to start it)."""
    try:
        w.jobs.run_now(job_id=job_id, job_parameters=params).result(timeout=ROLLBACK_TIMEOUT)
    except TimeoutError:
        return "still running"
    except Exception as e:  # the run failed; its row in the apply table says how far it got
        print("  the run ended with an error:", str(e)[:300])
    return None


def roll_back_once(job_id: int, apply_id: str) -> str:
    """One rollback of an execute run: a rollback dry run first, then the rollback that follows it. The job refuses a
    rollback that doesn't cite a finished dry run of the same execute run by the same requested_by, so the installer
    runs both with its own ids. Returns the status (SUCCEEDED, NEEDS_ATTENTION, FAILED, ...), or 'still running'."""
    print("rolling back apply", apply_id, "...")
    base = {"rollback_of": apply_id, "results_schema": RESULTS, "requested_by": me}
    dry_id, rollback_id = str(uuid.uuid4()), str(uuid.uuid4())
    print("  rollback dry run", dry_id[:8], "...")
    if run_apply_job(job_id, {**base, "mode": "rollback_dry_run", "apply_id": dry_id}) == "still running":
        return "still running"
    dry = run_status(dry_id)
    print("  dry run status:", dry)
    if dry in RUNNING_STATES:
        return "still running"
    if dry not in ("SUCCEEDED", "NEEDS_ATTENTION"):
        return f"rollback dry run {dry}"
    if run_apply_job(job_id, {**base, "mode": "rollback", "apply_id": rollback_id, "dry_run_id": dry_id}) == "still running":
        return "still running"
    status = run_status(rollback_id)
    print("  status:", status)
    if status == "not recorded":  # the job refused it (for example, the dry run had errors besides kept objects)
        return f"rollback refused after its dry run {dry_id}"
    return "still running" if status in RUNNING_STATES else status


def roll_back_all(st: dict) -> dict:
    """Rolls back this install's pending apply runs, newest first, in up to MAX_PASSES passes. NEEDS_ATTENTION is not
    fatal by itself: the run stays pending and is tried again while a pass makes progress. Returns the state after."""
    job_id = apply_job_ids()[0]
    last: dict[str, str] = {}
    pass_no = 0
    while True:
        pass_no += 1
        before = len(st["pending"])
        for p in st["pending"]:
            last[p["apply_id"]] = roll_back_once(job_id, p["apply_id"])
        st = apply_state()
        decision = progress_decision(before, len(st["pending"]), pass_no, MAX_PASSES)
        if decision == "done":
            return st
        if decision == "again":
            print(f"pass {pass_no} made progress; {len(st['pending'])} apply run(s) still pending, trying again")
            continue
        reason = ("the last pass made no progress" if decision == "stuck"
                  else f"still pending after {MAX_PASSES} passes")
        lines = []
        for p in st["pending"]:
            s = last.get(p["apply_id"], "not tried")
            if s == "still running":
                lines.append(f"- {p['apply_id']}: still running: wait for it to finish (Jobs > [{APP_NAME}] Unity Gateway "
                             "migration apply) and run uninstall again")
            elif s.startswith(("rollback refused", "rollback dry run")):
                # The app is stopped by now, so its Apply page can't be the first place to look: the job run says why.
                lines.append(f"- {p['apply_id']}: {s}: see why in the latest run of Jobs > [{APP_NAME}] Unity Gateway "
                             "migration apply (its output names the object it couldn't read or the check that refused "
                             "it), fix the cause, and run uninstall again. Or roll it back from the command line: "
                             + rollback_command(FOLDER, p["apply_id"]))
            else:
                lines.append(f"- {p['apply_id']}: {s}: open the app's Apply page for this run to see why, fix the cause "
                             "(the message names the grant or object), and run uninstall again. Or roll it back from the "
                             "command line: " + rollback_command(FOLDER, p["apply_id"]))
        raise ValueError(f"Uninstall stopped: the rollback of {len(st['pending'])} apply run(s) didn't finish ({reason}):\n"
                         + "\n".join(lines) + "\nThe app is stopped (start it again in Compute > Apps if you keep it). "
                         "Nothing else was removed: the app, jobs and files are still there.")


def delete_path(path: str) -> None:
    try:
        w.workspace.delete(path, recursive=True)
        print("deleted", path)
    except (NotFound, ResourceDoesNotExist):
        pass


if UNINSTALL:
    st = apply_state()
    marker_ok = MARKER_KIND == "ours"
    remove, keep, plan_problems, warnings = uninstall_plan(DROP, REMOVE_LOGS, ROLLBACK, st["pending"], st["logs"],
                                                           st["unmatched"], RESULTS, FOLDER, marker_ok)
    print("Uninstall removes:\n- " + "\n- ".join(remove))
    print("Uninstall keeps:\n- " + "\n- ".join(keep + ["the schemas where Apply created model services (uninstall never "
                                                     "removes a schema that holds services)"]))
    for line in warnings:
        print("WARNING:", line)
    blocked = PROBLEMS + plan_problems
    if ROLLBACK and st["pending"] and not apply_job_ids():
        blocked.append("the apply job of this app is missing, so its services can't be rolled back here: roll them back "
                       "with the command line (see the rollback command above) or restore the apply job")
    if PREVIEW:
        if blocked:
            print("Remove would stop:\n- " + "\n- ".join(blocked))
        print("\nNothing was changed. Set 1. Action = remove and run again to remove.")
        dbutils.notebook.exit("uninstall preview: nothing changed")
    if blocked:
        raise ValueError("Nothing was changed. Fix these first:\n- " + "\n- ".join(blocked))
    # 1. Stop the app first, so no new apply run starts while the rollback runs. A run after a stuck uninstall finds it
    # already stopped (the messages say "run uninstall again"), and the API refuses to stop an app whose compute
    # isn't active, so only an active app is stopped.
    if EXISTING_APP is not None:
        state = w.apps.get(APP_NAME).compute_status.state
        if state == apps.ComputeState.ACTIVE:
            print("stopping app", APP_NAME, "...")
            w.apps.stop_and_wait(APP_NAME)
        elif state in (apps.ComputeState.STOPPED, apps.ComputeState.ERROR):
            print("app", APP_NAME, "is", state.value, ": nothing to stop")
        else:  # starting, updating, deleting: it may still become active, so wait for it
            raise ValueError(f"Nothing was changed: the app {APP_NAME} is {state.value if state else 'in an unknown state'}. "
                             "Wait until it is ACTIVE or STOPPED in Compute > Apps, then run uninstall again")
    busy = active_job_names()
    if busy:
        raise ValueError("Uninstall stopped: these jobs have a run in progress: " + ", ".join(busy) + ". Wait for them to "
                         "finish in Jobs, then run uninstall again (the app is stopped; start it again in Compute > Apps "
                         "if you keep it)")
    # 2. Re-read what is pending, then 3. roll back, newest first.
    st = apply_state()
    remove, keep, plan_problems, warnings = uninstall_plan(DROP, REMOVE_LOGS, ROLLBACK, st["pending"], st["logs"],
                                                           st["unmatched"], RESULTS, FOLDER, marker_ok)
    if plan_problems:
        raise ValueError("Nothing was rolled back. Fix these first (the app is stopped; start it again in Compute > Apps "
                         "if you keep it):\n- " + "\n- ".join(plan_problems))
    if ROLLBACK and st["pending"]:
        st = roll_back_all(st)
    # 4. Cancel and delete the jobs, then the app.
    for j in MINE:
        w.jobs.cancel_all_runs(job_id=j["job_id"])
        w.jobs.delete(j["job_id"])
        print("deleted job", j["role"], j["job_id"])
    if EXISTING_APP is not None:
        w.apps.delete(APP_NAME)
        wait_app_gone()
        print("deleted app", APP_NAME)
    dash = find_dashboard_id()
    if dash:
        w.lakeview.trash(dash)
        print("moved dashboard to Trash:", DASH_NAME)
    # 5. Files: only the toolkit's own paths, and only when the marker says this folder is this app's.
    if marker_ok:
        delete_path(FILES)
        delete_path(f"{FOLDER}/output")
        if REMOVE_LOGS:
            for name in folder_children(f"{FOLDER}/apply_logs"):
                if name.endswith(".jsonl") or name == MARKER_NAME:
                    delete_path(f"{FOLDER}/apply_logs/{name}")
            if not folder_children(f"{FOLDER}/apply_logs"):
                delete_path(f"{FOLDER}/apply_logs")
        delete_path(MARKER)  # last: if anything above failed, the marker still says which install this is
        if not folder_children(FOLDER):
            delete_path(FOLDER)
    else:
        print("kept the files in", FOLDER, "(no toolkit marker for this app there)")
    # 6. Results tables, only the toolkit's, and the schema only if the toolkit made it and it's empty.
    if DROP:
        for t in RESULT_TABLES:
            spark.sql(f"DROP TABLE IF EXISTS `{CATALOG}`.`{SCHEMA}`.ug_migration_{t}")
        print("dropped results tables in", RESULTS)
        try:
            cmt = w.schemas.get(RESULTS).comment
        except (NotFound, ResourceDoesNotExist):
            cmt = None
        if schema_made_by_toolkit(cmt, APP_NAME):
            try:  # RESTRICT: only an empty schema goes
                spark.sql(f"DROP SCHEMA IF EXISTS `{CATALOG}`.`{SCHEMA}` RESTRICT")
                print("dropped schema", RESULTS)
            except Exception:
                print("kept schema", RESULTS, "(other objects are in it)")
        else:
            print("kept schema", RESULTS, "(the toolkit didn't create it)")
    remove, keep, _, _ = uninstall_plan(DROP, REMOVE_LOGS, ROLLBACK, st["pending"], st["logs"], st["unmatched"], RESULTS,
                                        FOLDER, marker_ok)
    print("Done. Kept:\n- " + "\n- ".join(keep) if keep else "Done.")
    dbutils.notebook.exit("uninstalled")

# COMMAND ----------

print("Checklist:\n" + "\n".join(checklist_lines(CHECKS + [("fix", p, "") for p in PROBLEMS])))
if PROBLEMS:
    raise ValueError("Nothing was changed. Fix the FIX items in the checklist above, then Run all again:\n- "
                     + "\n- ".join(PROBLEMS))
print("This install creates or updates:\n" + "\n".join(creates_lines(FOLDER, RESULTS, TARGET, TARGET_STATE["state"],
                                                                     APP_NAME, JOB_IDENTITY)))
print(f"install: {VERSION_NOTE}")
print(f"The jobs will run as {JOB_IDENTITY}. At the end, the first snapshot starts: it reads account-wide system tables "
      "(legacy endpoints and traffic for every workspace in the account) and writes them to the results schema.")
if RUN_AS:
    print(f"The checks above ran as you ({me}). Service principal {RUN_AS} needs the same access: SELECT on the system "
          "tables, USE and CREATE on the results schema, and USE CATALOG, USE SCHEMA and CREATE SERVICE on the target schema.")

# COMMAND ----------

# MAGIC %md ## 1. Toolkit files

# COMMAND ----------

PAYLOAD = ""

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
if RUN_AS:  # the jobs read the toolkit files and write apply logs in the install folder
    from databricks.sdk.service.workspace import WorkspaceObjectAccessControlRequest, WorkspaceObjectPermissionLevel
    try:
        folder_id = w.workspace.get_status(FOLDER).object_id
        w.workspace.update_permissions("directories", str(folder_id), access_control_list=[
            WorkspaceObjectAccessControlRequest(service_principal_name=RUN_AS,
                                                permission_level=WorkspaceObjectPermissionLevel.CAN_MANAGE)])
        print(f"gave service principal {RUN_AS} CAN MANAGE on {FOLDER}")
    except DatabricksError as e:
        print(f"WARNING: couldn't give service principal {RUN_AS} CAN MANAGE on {FOLDER} ({str(e)[:200]}): set it in "
              "the folder's Share dialog, or the jobs can't read the toolkit files or write apply logs")

# COMMAND ----------

# MAGIC %md ## 2. Schemas: results, and new model services

# COMMAND ----------

# Created with its comment if it's new. An existing schema keeps its comment (it may be yours).
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}` COMMENT 'Unity Gateway migration app results (app: {APP_NAME})'")
print("schema ready:", RESULTS)
# Bring the results tables up to date now (new columns, such as a run's workspace), with the same code the jobs use:
# the updated app reads them before any job of this version has run.
try:
    if "/Workspace" + FILES not in sys.path:
        sys.path.insert(0, "/Workspace" + FILES)
    import ug_migration_store as _store
    _store.ensure_tables(spark, RESULTS)
    print("results tables ready")
except Exception as e:  # the jobs add the columns on their first run anyway
    print(f"note: couldn't update the results tables now ({str(e)[:200]}); the jobs do it on their first run")
# The schema for new model services: the checks created it if it was missing (and 8 allowed it). When the jobs run as
# a service principal, it gets what Apply needs there. A failed grant isn't fatal: the apply job reports it.
if RUN_AS and TARGET_STATE["state"] in ("exists", "created"):
    for stmt in target_grants(TARGET, RUN_AS):
        try:
            spark.sql(stmt.rstrip(";"))
            print("granted:", stmt)
        except Exception as e:  # not the owner of the catalog or schema: printed for an admin
            print(f"note: couldn't run {stmt} ({str(e)[:160]}); ask the owner to run it")

# COMMAND ----------

# MAGIC %md ## 3. Jobs

# COMMAND ----------

SPECS = job_specs(APP_NAME, FOLDER, RESULTS, WAREHOUSE_ID, SECRET_SCHEMAS, ALLOW_SECRET_READ, DEADLINE, RUN_AS,
                  CENTRAL_WORKSPACES, CENTRAL_SECRET, TARGET)
print(f"The jobs run as {JOB_IDENTITY}" + ("" if RUN_AS else " (set 7. Run jobs as service principal (custom setup: 4. Setup = custom) to change it)"))
JOB_IDS = {}


def job_write(fn, *args, **kwargs):
    """jobs.create/reset, with the fix spelled out when the run-as service principal can't be bound to the job."""
    try:
        return fn(*args, **kwargs)
    except PermissionDenied as e:
        if RUN_AS and "servicePrincipal.user" in str(e):
            raise PermissionDenied(f"the jobs run as service principal {RUN_AS}, and you don't have its Service "
                                   "principal: User role: " + RUN_AS_ROLE_FIX.format(sp=RUN_AS)) from e
        raise


for role, settings in SPECS.items():
    current_jobs = sorted(i["job_id"] for i in MINE if i["role"] == role)
    if current_jobs:
        keep_id, *extra = current_jobs
        if settings.schedule:  # keep the schedule's paused/unpaused state across updates
            current = w.jobs.get(keep_id).settings.schedule
            if current and current.pause_status:
                settings.schedule.pause_status = current.pause_status
        job_write(w.jobs.reset, keep_id, settings)
        JOB_IDS[role] = keep_id
        print("updated job", role, keep_id)
        for job_id in extra:  # left over from an interrupted earlier run
            w.jobs.delete(job_id)
            print("removed duplicate job", role, job_id)
    else:
        JOB_IDS[role] = job_write(w.jobs.create, **settings.as_shallow_dict()).job_id
        print("created job", role, JOB_IDS[role])

# COMMAND ----------

# MAGIC %md ## 4. App

# COMMAND ----------

resources = app_resources(WAREHOUSE_ID, JOB_IDS)
existing_app = get_app()
if existing_app is not None and app_deleting(existing_app):  # left from an uninstall that just ran
    print(f"app {APP_NAME} is still being deleted: waiting for it to go...")
    wait_app_gone()
    existing_app = None
if existing_app is not None and app_create_failed(existing_app):  # it can't be updated, and holds nothing to keep
    print(f"app {APP_NAME} is left from a create that failed ({app_error(existing_app)[:200]}): removing it to create it "
          "again...")
    w.apps.delete(APP_NAME)
    wait_app_gone()
    existing_app = None
if existing_app:
    # Partial update: only the fields the installer owns, so budget/usage policy, compute size and the rest stay as
    # the admin set them. Seen live 2026-10-31: the older full-replace apps.update refuses compute size changes.
    try:
        w.apps.create_update_and_wait(APP_NAME, APP_UPDATE_MASK, app=apps.App(
            name=APP_NAME, description=APP_DESCRIPTION, resources=resources, user_api_scopes=["sql"]))
    except (NotFound, ApiNotImplemented, AttributeError):  # workspaces or SDKs without the update API; others raise
        spec = app_update_spec(existing_app, name=APP_NAME, description=APP_DESCRIPTION, resources=resources,
                               user_api_scopes=["sql"])
        spec.compute_size = None  # the full-replace API refuses compute size
        w.apps.update(APP_NAME, spec)
    print("updated app", APP_NAME)
else:
    print("creating app (a few minutes)...")
    try:
        w.apps.create_and_wait(apps.App(name=APP_NAME, resources=resources, user_api_scopes=["sql"],
                                        description=APP_DESCRIPTION))
    except OperationFailed as e:
        failed = get_app()
        reason = app_error(failed) if failed is not None else str(e)
        raise OperationFailed(f"Databricks couldn't create app {APP_NAME}: {reason[:400]}. The jobs and files are in "
                              "place. Fix the cause (or wait, if it's a temporary limit), then run the installer again: "
                              "it removes the failed app and creates it again.") from e
app = get_app()
if app.compute_status and app.compute_status.state and app.compute_status.state.value not in ("ACTIVE", "STARTING"):
    w.apps.start_and_wait(APP_NAME)

deployment = apps.AppDeployment(
    source_code_path=f"{FILES}/app",
    command=["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
    env_vars=app_env(RESULTS, OPERATOR_LIST, TOOLKIT_VERSION, SECRET_SCHEMAS, ALLOW_SECRET_READ, DEADLINE,
                     CENTRAL_WORKSPACES, HUB_WORKSPACE_ID, TARGET))
print("deploying app...")
d = w.apps.deploy_and_wait(APP_NAME, deployment)
print("deployment:", d.status.state.value if d.status and d.status.state else d.status)

# COMMAND ----------

# The install marker records the version, so the next run can show from -> to and refuse a silent downgrade.
w.workspace.upload(MARKER, io.BytesIO(marker_text(APP_NAME, TOOLKIT_VERSION, RESULTS, FOLDER, me, TARGET,
                                                  CREATE_TARGET, OPERATOR_LIST).encode()),
                   format=ImportFormat.AUTO, overwrite=True)
print(f"installed {TOOLKIT_VERSION} ({VERSION_NOTE})")

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

# MAGIC %md ## 6. Finish: first run and the target schema

# COMMAND ----------

app = w.apps.get(APP_NAME)
host = w.config.host.rstrip("/")
for r, i in JOB_IDS.items():
    print(f"Job ({r}):", f"{host}/jobs/{i}")
print(f"Starting the first snapshot as {JOB_IDENTITY}. It reads account-wide system tables: legacy endpoints and "
      f"traffic for every workspace in the account, not only this one, and writes them to {RESULTS}.")
try:  # starts the first snapshot without waiting, so the Overview has data in a few minutes
    snap = w.jobs.run_now(job_id=JOB_IDS["snapshot"], job_parameters={"requested_by": me})
    snapshot_note = f"First snapshot started: {host}/jobs/{JOB_IDS['snapshot']}/runs/{snap.run_id} (Overview fills in within a few minutes)."
except DatabricksError as e:
    snapshot_note = (f"The first snapshot didn't start ({str(e)[:200]}): in the app, open Overview and click Refresh snapshot.")
try:
    w.schemas.get(TARGET)
    target_note = (f"New model services go to {TARGET} ({'created by this install' if TARGET_STATE['state'] == 'created' else 'it exists'}). "
                   f"That name ends up in your callers' code (catalog.schema.service), so change it now if you want another "
                   f"one: set 3. Schema for new model services and Run all again. The apply job runs as {JOB_IDENTITY}: it "
                   "needs USE CATALOG, USE SCHEMA and CREATE SERVICE there.")
except (NotFound, ResourceDoesNotExist):
    target_note = (f"New model services go to {TARGET}, which doesn't exist yet. Scans work; Apply waits until it exists. "
                   "Run this as a catalog admin, or ask one:\n  " + "\n  ".join(target_schema_lines(TARGET, RUN_AS or me)))
except DatabricksError as e:  # you can't see it: it may exist
    target_note = (f"New model services go to {TARGET}, which you can't check ({str(e)[:120]}). If it doesn't exist, ask a "
                   "catalog admin to run:\n  " + "\n  ".join(target_schema_lines(TARGET, RUN_AS or me)))
print("App:", app.url)
print(f"Open the app: {app.url}  (or Compute > Apps > {APP_NAME})")
print("First steps: wait for the snapshot (a few minutes), then in the app open Scans and click Start scan.")
print(snapshot_note)
print(f"The weekly snapshot job is paused. To run it every Monday at 06:00 UTC, open Jobs > [{APP_NAME}] Unity Gateway "
      "migration snapshot, and unpause its schedule.")
print(target_note)
print("Unity Catalog secret mapping is off. To turn it on, set 4. Setup to custom and click Run all, then set 11. Allowed "
      "secret schemas to the catalog.schema that holds the secrets (for example main.secrets) and Run all again; grant the "
      "apply job's identity READ on them.")
print(f"Results: {RESULTS}. Operators: {', '.join(OPERATOR_LIST) or '(none)'}. Jobs run as {JOB_IDENTITY}. Version {TOOLKIT_VERSION}. "
      f"The user guide is in {FILES}/USER_GUIDE.md.")
displayHTML(f"""
<h3>Unity Gateway Migration Toolkit is installed</h3>
<p><b>Open the app:</b> <a href="{app.url}" target="_blank">{app.url}</a> (Compute &gt; Apps &gt; {APP_NAME})</p>
<p>Jobs: {", ".join(f'<a href="{host}/jobs/{i}" target="_blank">{r}</a>' for r, i in JOB_IDS.items())}</p>
<p>The first snapshot reads account-wide system tables (every workspace in the account).</p>
<p>First steps: wait for the snapshot (Overview), then <b>Scans</b> &gt; Start scan. {snapshot_note}</p>
<p>The weekly snapshot job is paused: unpause its schedule in Jobs to run it every Monday.</p>
<p>{target_note}</p>
<p>Operators: {", ".join(OPERATOR_LIST) or "(none)"}. Results: {RESULTS}. Jobs run as {JOB_IDENTITY}. Version {TOOLKIT_VERSION}.</p>
<p>To let others view results, run (replace <code>migration-team</code> with your group):<br>
<code>GRANT USE CATALOG ON CATALOG `{CATALOG}` TO `migration-team`;<br>
GRANT USE SCHEMA, SELECT ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `migration-team`;</code></p>
""")

# COMMAND ----------

# Also return the links as the notebook result, so they're visible when the installer runs as a job.
dbutils.notebook.exit(json.dumps({"app": app.url, "version": TOOLKIT_VERSION,
                                  "jobs": {r: f"{host}/jobs/{i}" for r, i in JOB_IDS.items()}}))
