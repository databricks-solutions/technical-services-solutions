# Databricks notebook source
# MAGIC %md
# MAGIC # Install the Unity Gateway Migration Toolkit
# MAGIC
# MAGIC Installing and using the app needs no CLI: this one notebook installs everything inside this workspace (no Git, no local setup).
# MAGIC
# MAGIC 1. In the **settings cell** below, check the `install(...)` call. Every setting has a default: `catalog=None` uses
# MAGIC    the workspace's default catalog and `warehouse=None` the running SQL warehouse (an update keeps the ones it has).
# MAGIC 2. Click **Run all**. It takes about 5 minutes; the link to the app is printed at the end.
# MAGIC
# MAGIC What it creates (the jobs are tagged `Project = unity-gateway-migration-toolkit`, so the usage of this toolkit can be identified):
# MAGIC - The toolkit files in the install folder (replaced on every run, so files removed from a newer version don't linger).
# MAGIC - The results schema (if it doesn't exist).
# MAGIC - Three Lakeflow jobs the app starts: account snapshot (weekly schedule, paused), workspace scan, and apply/rollback.
# MAGIC - The **Unity Gateway Migration Toolkit** app (charts and exports are in the app).
# MAGIC
# MAGIC **Before anything is changed**, the notebook checks the workspace (Apps, catalog and schema privileges, the SQL
# MAGIC warehouse, system tables, the install folder, and whether another toolkit install already uses the same app name,
# MAGIC results schema or folder). If a check fails, nothing is changed, and the message says what to change and who to ask.
# MAGIC
# MAGIC **Who the jobs run as:** you (the person running this notebook), unless `run_as` is set to a service principal's
# MAGIC application ID. Scans and apply act with that identity's permissions, so use a workspace admin with access to the
# MAGIC system tables, or a service principal for a shared install (you need the Service Principal User role on it).
# MAGIC
# MAGIC **The first snapshot starts at the end of the install** and reads account-wide system tables: legacy endpoints
# MAGIC and traffic for every workspace in the account, not only this one. It writes them to the results schema.
# MAGIC **Operators** are the people who can start jobs from the app; everyone else can only view results. You are the
# MAGIC first operator. Workspace admins add others in the app (**Settings**).
# MAGIC
# MAGIC Run it again to update (same settings). To remove it, call `uninstall(preview=True)` instead of `install(...)` to see
# MAGIC what would be removed and kept, then `uninstall(preview=False)`. Uninstall refuses while a toolkit job is running.
# MAGIC
# MAGIC Prototype from Databricks Shared Technical Services, provided as is. Version __VERSION__.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk==0.158.0"
# MAGIC %restart_python

# COMMAND ----------

# Don't edit this cell: the settings are in the next one.
PARAMS: dict = {}


def install(catalog=None, warehouse=None, schema=None, app_name="ug-migration-toolkit", folder=None, run_as=None,
            secret_schemas=None, allow_secret_read=False, deadline=None, central_workspaces=None, central_secret=None,
            adopt_app=False, allow_downgrade=False, second_install=False):
    """Installs or updates the toolkit. None means the default.

    catalog: results catalog (you need USE CATALOG and CREATE SCHEMA). None = the existing install's, else the
        workspace's default catalog.
    warehouse: SQL warehouse name or ID. None = the existing install's, else the only running one (or the only one).
    schema: results schema. None = ug_migration for the default app, else the app name with - as _.
    app_name: 2-30 lowercase letters, digits or hyphens.
    folder: install folder. None = your home folder/<app name> (ending -toolkit).
    run_as: run the jobs as this service principal (application ID). None = the jobs run as you.
    secret_schemas: catalog.schema list apply may map Unity Catalog secrets from. None = off.
    allow_secret_read: True lets apply copy legacy secret values, in plain text, into the new services (risk: keep False
        unless needed).
    deadline: legacy deadline, YYYY-MM-DD. None = 2027-03-30.
    central_workspaces: central mode, the workspace IDs to manage. None = off.
    central_secret: central mode, scope/key holding the run_as service principal's OAuth client secret.
    adopt_app: True takes over an existing app of this name (it's overwritten).
    allow_downgrade: True installs an older version over a newer one.
    second_install: True allows a second install (other app name, results schema and install folder).
    """
    PARAMS.clear()
    PARAMS.update(locals(), action="install")


def uninstall(preview=True, catalog=None, warehouse=None, schema=None, app_name="ug-migration-toolkit", folder=None,
              drop_data=False, remove_logs=False, rollback_services=False, adopt_app=False):
    """Removes the toolkit. preview=True (the default) only shows what would be removed and kept.

    drop_data: True also removes the results tables (and the schema, if the toolkit made it and it's empty).
    remove_logs: True removes the apply logs (False keeps them, so kept services can be rolled back later).
    rollback_services: True rolls back the services created by apply too.
    adopt_app: True removes an app of this name that isn't a toolkit app.
    catalog, warehouse, schema, app_name, folder: as in install(); None finds them from the install.
    """
    PARAMS.clear()
    PARAMS.update(locals(), action="uninstall: preview" if preview else "uninstall: remove")
    PARAMS.pop("preview")

# COMMAND ----------

# Settings: edit, then click Run all. A setting left out (or None) uses its default; help(install) lists them all.
install(
    catalog=None,    # results catalog; None = the existing install's, else the workspace's default catalog
    warehouse=None,  # SQL warehouse name or ID; None = the existing install's, else the running one
)

# To remove the toolkit, replace the call above with uninstall(preview=True), then uninstall(preview=False).

# COMMAND ----------

# HELPERS-BEGIN
# Pure helpers: no workspace calls. test_installer.py runs this block, so keep it free of dbutils, spark and w.
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
MARKER_NAME = "ug_migration_toolkit.marker"
TOOLKIT_NAMES = ("files", "output", "apply_logs", MARKER_NAME)  # what a toolkit folder holds
RESULT_TABLES = ("scans", "scan_items", "applies", "apply_items", "workspaces", "endpoints", "operators")
SYSTEM_TABLES = ("system.serving.endpoint_usage", "system.serving.served_entities", "system.ai_gateway.usage",
                 "system.access.workspaces_latest")  # read by the snapshot and the scans
TARGET_CATALOG, TARGET_SCHEMA = "ai_gateway", "migrated"  # the scan form's default target, where apply creates services
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
        return (f"this would downgrade the toolkit from {prev} to {now}: set allow_downgrade=True to do it anyway")
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
        return schemas, "secret_schemas must be catalog.schema, comma-separated: " + ", ".join(bad)
    return schemas, None


DEFAULT_DEADLINE = "2027-03-30"  # the legacy serving deadline for v1 and v2 (confirmed as of 2026-11-01)


def valid_deadline(text: str) -> str | None:
    """None when the legacy deadline is an ISO date (YYYY-MM-DD), else the problem to show."""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except (TypeError, ValueError):
        return f"deadline must be a date as YYYY-MM-DD (not {text!r})"
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
    """Problem with run_as, or None. Blank is fine (the jobs run as the installer)."""
    if application_id and not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                                           application_id):
        return ("run_as must be the service principal's application ID (a UUID like "
                f"12345678-1234-1234-1234-123456789012), not {application_id!r}")
    return None


def central_problems(workspaces: str, secret_ref: str, run_as: str) -> tuple[list[str], list[str]]:
    """Central mode (optional): the allowlist and the problems with the two settings. Blank workspaces = off.

    It scans other workspaces as the jobs' run-as service principal, so it needs that identity and a secret
    scope/key holding the service principal's OAuth secret (the value is only read by the scan job)."""
    ids, problems = [], []
    for part in (workspaces or "").split(","):
        p = part.strip()
        if not p:
            continue
        if not re.fullmatch(r"[0-9]{1,20}", p):
            problems.append(f"central_workspaces takes workspace IDs (numbers), not {p!r}")
        elif p not in ids:
            ids.append(p)
    ref = (secret_ref or "").strip()
    if ids or ref:
        if not ids:
            problems.append("central_secret is set, but central_workspaces isn't")
        if not run_as:
            problems.append("central mode scans other workspaces as a service principal: set run_as to its "
                            "application ID")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", ref):
            problems.append("central_secret must be scope/key (the secret "
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
              central_workspaces: list[str] | None = None, central_secret: str = "") -> dict[str, jobs.JobSettings]:
    """The three toolkit jobs. Parameter names match the notebooks in notebook/ and the bundle's databricks.yml.
    run_as: a service principal's application ID to run them as; blank runs them as the installing user.
    central_workspaces / central_secret: central mode (the scan and apply jobs may act on these other workspaces)."""
    P = jobs.JobParameterDefinition
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
            P("scan_roots", ""), P("target_catalog", TARGET_CATALOG), P("target_schema", TARGET_SCHEMA),
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
            hub_workspace_id: str = "") -> list[apps.EnvVar]:
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
        E(name="UGMIG_MAX_SCAN_AGE_DAYS", value="14"), E(name="UGMIG_DEADLINE", value=deadline)]


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
                    "moved to them keep working (to remove them, set rollback_services=True)")
        if remove_logs:
            problems.append("the apply logs are needed to roll back the kept services later: set remove_logs=False, or set rollback_services=True")
        missing = [a for a in ids if a not in logs]
        if drop and missing:
            problems.append(f"no apply log for apply run(s) {', '.join(missing)} in {folder}/apply_logs, so their services "
                            "couldn't be rolled back later: set rollback_services=True, or keep the results "
                            "tables (drop_data=False)")
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
                        "tables (drop_data=False)")
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


def target_schema_lines(me: str) -> list[str]:
    t = f"`{TARGET_CATALOG}`.`{TARGET_SCHEMA}`"
    return [f"CREATE SCHEMA IF NOT EXISTS {t};",
            f"GRANT USE CATALOG ON CATALOG `{TARGET_CATALOG}` TO `{me}`;",
            f"GRANT USE SCHEMA, CREATE SERVICE ON SCHEMA {t} TO `{me}`;"]


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


# The settings of install() and uninstall() in the settings cell, and their defaults.
SETTINGS = {"action": "install", "catalog": None, "warehouse": None, "schema": None, "app_name": DEFAULT_APP,
            "folder": None, "run_as": None, "secret_schemas": None, "allow_secret_read": False, "deadline": None,
            "central_workspaces": None, "central_secret": None, "adopt_app": False, "allow_downgrade": False,
            "second_install": False, "drop_data": False, "remove_logs": False, "rollback_services": False}
LIST_SETTINGS = ("secret_schemas", "central_workspaces")  # a list, or text with commas


def settings_from(params: dict) -> tuple[dict, list[str]]:
    """The settings of the install() or uninstall() call (text and True/False), and the problems with their types."""
    out = {k: v if isinstance(v, bool) else v or "" for k, v in SETTINGS.items()}
    if not params.get("action"):
        return out, ["call install(...) or uninstall(...) in the settings cell, then Run all"]
    problems = []
    for key, value in params.items():
        default = SETTINGS[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                problems.append(f"{key} must be True or False, not {value!r}")
            out[key] = value is True
        elif value is None:
            out[key] = default or ""
        elif key in LIST_SETTINGS and isinstance(value, (list, tuple, set)):
            out[key] = ",".join(str(x).strip() for x in value)
        elif isinstance(value, str):
            out[key] = value.strip()
        else:
            problems.append(f"{key} must be text, not {value!r}")
            out[key] = ""
    return out, problems


def pick_warehouse(given: str, warehouses: list, current_id: str = "") -> tuple[str, str | None]:
    """The SQL warehouse ID to use, or a problem. given: a name or ID. Blank: the existing install's warehouse, else
    the only running one, else the only one. Never a guess between several."""
    by_id = {x.id: x for x in warehouses if x.id}
    names = ", ".join(sorted(f"{x.name} ({x.id})" for x in warehouses)) or "none"
    if given:
        if given in by_id:
            return given, None
        hits = [x.id for x in warehouses if (x.name or "").lower() == given.lower()]
        if len(hits) == 1:
            return hits[0], None
        return "", (f"warehouse {given!r} " + ("matches several warehouses: use its ID" if hits else "wasn't found")
                    + f" (the ones you can use: {names})")
    if current_id in by_id:
        return current_id, None
    running = [x.id for x in warehouses if x.state is not None and x.state.value == "RUNNING"]
    if len(running) == 1:
        return running[0], None
    if len(warehouses) == 1:
        return warehouses[0].id, None
    if not warehouses:
        return "", "no SQL warehouse found: ask a workspace admin to create one or give you CAN USE on one"
    return "", f"set warehouse= to the name or ID of one of these SQL warehouses: {names}"


def pick_catalog(default_catalog: str | None) -> tuple[str, str | None]:
    """The results catalog when catalog= is blank: the workspace's default catalog, unless it can't hold the results."""
    if default_catalog and default_catalog not in ("hive_metastore", "system", "samples"):
        return default_catalog, None
    return "", ("set catalog= to a catalog where you can create a schema (USE CATALOG and CREATE SCHEMA): the "
                f"workspace's default catalog ({default_catalog or 'none'}) can't hold the results")


OPERATORS_TABLE = "ug_migration_operators"  # the app's operators: workspace admins edit it in the app (Settings)


def operators_table_sql(catalog: str, schema: str) -> str:
    return (f"CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.{OPERATORS_TABLE} (email STRING NOT NULL, added_by "
            "STRING, added_at TIMESTAMP) COMMENT 'Unity Gateway migration app operators (edited in the app: Settings)'")


def operator_grants(catalog: str, schema: str, app_sp: str) -> list[str]:
    """What the app's service principal needs to read and edit the operators table, and nothing else."""
    return [f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{app_sp}`",
            f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.`{schema}` TO `{app_sp}`",
            f"GRANT SELECT, MODIFY ON TABLE `{catalog}`.`{schema}`.{OPERATORS_TABLE} TO `{app_sp}`"]


def operators_to_seed(existing: list[str], me: str, is_sp: bool) -> list[str]:
    """Who to add to an empty operators table: you (a person; a service principal isn't an operator). Nobody when the
    table has rows: the app owns the list after the first install."""
    return [] if existing or is_sp else [me.lower()]


# HELPERS-END

# COMMAND ----------

# The pip cell restarted Python, so the client and the signed-in user are created again here.
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
me_user = w.current_user.me()
me = me_user.user_name

S, problems = settings_from(PARAMS)
ACTION = S["action"]
UNINSTALL = ACTION.startswith("uninstall")
PREVIEW = ACTION == "uninstall: preview"
APP_NAME = S["app_name"]
CATALOG = S["catalog"]
CATALOG_GIVEN = bool(CATALOG)
SCHEMA_GIVEN = bool(S["schema"])
SCHEMA = results_schema_for(S["schema"], APP_NAME)
RESULTS = f"{CATALOG}.{SCHEMA}"
WAREHOUSE_GIVEN = S["warehouse"]
WAREHOUSE_ID = ""  # chosen once the existing install is known (below)
IS_SP = is_service_principal(me)
FOLDER_GIVEN = bool(S["folder"])
FOLDER = folder_for(S["folder"], me, APP_NAME)
FILES = f"{FOLDER}/files"
MARKER = f"{FOLDER}/{MARKER_NAME}"
ADOPT = S["adopt_app"]
ALLOW_DOWNGRADE = S["allow_downgrade"]
SECOND_INSTALL = S["second_install"]
ALLOW_SECRET_READ = S["allow_secret_read"]
SECRET_SCHEMAS, secret_problem = parse_secret_schemas(S["secret_schemas"])
DEADLINE = S["deadline"] or DEFAULT_DEADLINE
deadline_problem = valid_deadline(DEADLINE)
RUN_AS = S["run_as"]
run_as_problem = valid_run_as(RUN_AS)
CENTRAL_WORKSPACES, central_problem_list = central_problems(S["central_workspaces"], S["central_secret"], RUN_AS)
CENTRAL_SECRET = S["central_secret"] if CENTRAL_WORKSPACES else ""
try:  # the same source the jobs and scans use (x-databricks-org-id): get_workspace_id() can differ on some workspaces
    import requests as _requests
    _org = _requests.get(f"{w.config.host.rstrip('/')}/api/2.0/clusters/spark-versions",
                         headers=w.config.authenticate(), timeout=30).headers.get("x-databricks-org-id")
    HUB_WORKSPACE_ID = str(_org or w.get_workspace_id())
except Exception:
    HUB_WORKSPACE_ID = ""
JOB_IDENTITY = f"service principal {RUN_AS}" if RUN_AS else me
TOOLKIT_VERSION = "__VERSION__"
APP_DESCRIPTION = f"{APP_MARKER}: account overview, workspace scans, readiness, code fixes and apply"
DROP = S["drop_data"]
REMOVE_LOGS = S["remove_logs"]
ROLLBACK = S["rollback_services"]

if CATALOG_GIVEN and not re.fullmatch(NAME, CATALOG):
    problems.append("catalog must use letters, digits and underscores")
if not re.fullmatch(NAME, SCHEMA):
    problems.append("schema must use letters, digits and underscores")
if not valid_app_name(APP_NAME):
    problems.append(f"app_name must be 2-30 lowercase letters, digits or hyphens (not {APP_NAME!r})")
if valid_folder(FOLDER):
    problems.append(valid_folder(FOLDER) + f" (folder is {FOLDER!r})")
if secret_problem:
    problems.append(secret_problem)
if deadline_problem:
    problems.append(deadline_problem)
if run_as_problem:
    problems.append(run_as_problem)
problems += central_problem_list
if problems:
    raise ValueError("Fix the settings first: " + "; ".join(problems))

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
        # jobs.list leaves out the job parameters (seen live 2026-11-12), and the results schema is one of them.
        s = w.jobs.get(j.job_id).settings or s
        params = {p.name: p.default for p in (s.parameters or [])}
        results = params.get("results_schema") or params.get("snapshot_table", "").rsplit(".", 1)[0]
        path = s.tasks[0].notebook_task.notebook_path if s.tasks and s.tasks[0].notebook_task else ""
        out.append({"job_id": j.job_id, "name": s.name or "", "app": app_from_job(s.name, tags),
                    "role": tags.get("role", ""), "results": results if "." in results else "",
                    "folder": install_folder_of(path)})
    return out


def toolkit_app_names() -> list[str]:
    return [a.name for a in w.apps.list() if is_toolkit_app(a.description)]


INSTALLS = toolkit_installs()  # read once; the checks and steps below use it
MINE = [i for i in INSTALLS if i["app"] == APP_NAME]
EXISTING_APP = get_app()


def adopt_existing_locations() -> None:
    """Blank settings keep the locations this app was installed with (earlier versions used other defaults), so an
    update doesn't split the install. A setting with a value must agree with the existing install, or the run stops."""
    global CATALOG, SCHEMA, RESULTS, FOLDER, FILES, MARKER
    results = next((i["results"] for i in MINE if i["results"]), "")
    folder = next((i["folder"] for i in MINE if i["folder"]), "")
    if results:
        rc, rs = results.split(".", 1)
        if not SCHEMA_GIVEN and CATALOG_GIVEN and CATALOG != rc:
            raise ValueError(f"catalog is {CATALOG}, but app {APP_NAME} already keeps its results in "
                             f"{results}. Pick catalog {rc} to update it, or choose another app_name for a second install "
                             "(second_install=True)")
        if not SCHEMA_GIVEN:
            CATALOG, SCHEMA = rc, rs
            print("using the results schema of the existing install:", results)
        elif not CATALOG_GIVEN:
            CATALOG = rc
    RESULTS = f"{CATALOG}.{SCHEMA}"
    if results and RESULTS != results:
        raise ValueError(f"app {APP_NAME} is installed with its results in {results}, not {RESULTS}: leave schema "
                         "blank and set that catalog to update it, or choose another app_name for a second install")
    if folder:
        if not FOLDER_GIVEN:
            FOLDER = folder
            print("using the install folder of the existing install:", FOLDER)
        elif FOLDER != folder:
            raise ValueError(f"app {APP_NAME} is installed in {folder}, not {FOLDER}: leave folder blank "
                             "to update it, or choose another app_name for a second install")
    FILES = f"{FOLDER}/files"
    MARKER = f"{FOLDER}/{MARKER_NAME}"


def default_catalog() -> str | None:
    """The workspace's default catalog (the default namespace setting, else the metastore assignment's)."""
    try:
        return w.settings.default_namespace.get().namespace.value
    except Exception:  # not set, or not readable: the metastore assignment has the older copy
        pass
    try:
        return w.metastores.current().default_catalog_name
    except Exception:
        return None


adopt_existing_locations()
if UNINSTALL and not MINE and not EXISTING_APP and not exists(MARKER):
    found = install_names(INSTALLS, toolkit_app_names())
    unnamed = [j["name"] for j in INSTALLS if not j["app"]]
    raise ValueError(f"no install named {APP_NAME}; found: {', '.join(found) or 'no toolkit installs in this workspace'}"
                     + (f". Also {len(unnamed)} toolkit job(s) deployed by the bundle without an app name (not managed "
                        "here): " + ", ".join(unnamed) if unnamed else ""))
if UNINSTALL and not CATALOG:
    raise ValueError("set catalog= in uninstall(...): this install's results schema isn't recorded in its jobs")
if not CATALOG:
    CATALOG, catalog_problem = pick_catalog(default_catalog())
    if catalog_problem:
        raise ValueError(catalog_problem)
    RESULTS = f"{CATALOG}.{SCHEMA}"
    print("results catalog (the workspace's default):", CATALOG)
_current_wh = next((r.sql_warehouse.id for r in (EXISTING_APP.resources or []) if r.sql_warehouse), "") \
    if EXISTING_APP else ""
WAREHOUSE_ID, _wh_problem = pick_warehouse(WAREHOUSE_GIVEN, list(w.warehouses.list()), _current_wh)
if _wh_problem and not UNINSTALL:
    raise ValueError(_wh_problem)
MARKER_KIND, MARKER_APP = marker_status(read_marker(), APP_NAME)
print(f"{ACTION}: app {APP_NAME}, results {RESULTS}, folder {FOLDER}, warehouse {WAREHOUSE_ID or '(none)'}, "
      f"jobs run as {me}")


def run_sql(statement: str) -> str | None:
    """None if the statement succeeds on the chosen warehouse, else the error text."""
    r = w.statement_execution.execute_statement(statement=statement, warehouse_id=WAREHOUSE_ID, wait_timeout="50s")
    if r.status and r.status.state and r.status.state.value == "SUCCEEDED":
        return None
    if r.status and r.status.error:
        return r.status.error.message
    return f"state {r.status.state.value if r.status and r.status.state else 'unknown'}"


def start_warehouse() -> str | None:
    """Starts the SQL warehouse if it's stopped and waits until it runs. Returns a problem, or None."""
    try:
        wh = w.warehouses.get(WAREHOUSE_ID)
    except (NotFound, ResourceDoesNotExist):
        return "the SQL warehouse wasn't found: set warehouse= to another one"
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
                "another one with warehouse=), then run the installer again")
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


def preflight() -> tuple[list[str], list[str], str]:
    """Checks before anything is created, changed or deleted. Returns (problems, notes, version note). The only writes:
    the SQL warehouse is started if stopped, and the results schema is created as the last check, when it's missing and
    everything else passed (the step would create it anyway)."""
    found, notes = [], []
    try:
        next(iter(w.apps.list(page_size=1)), None)
    except DatabricksError as e:
        return [f"Databricks Apps isn't usable here ({str(e)[:200]}): ask a workspace admin to enable Apps for you, or to "
                "let you create apps"], notes, ""
    unnamed = [j["name"] for j in INSTALLS if not j["app"]]
    if unnamed:
        notes.append(f"{len(unnamed)} toolkit job(s) deployed by the bundle have no app name and aren't managed by this "
                     "installer (left alone): " + ", ".join(unnamed))
    if EXISTING_APP and not is_toolkit_app(EXISTING_APP.description) and not ADOPT:
        found.append(f"an app named {APP_NAME} exists and isn't a toolkit app: " + (
            "choose another app_name, or set adopt_app=True if it can be replaced" if not UNINSTALL
            else "uninstall won't delete it (set adopt_app=True to delete it anyway)"))
    bundle_jobs = [j["name"] for j in MINE if bundle_made(j["name"], APP_NAME)]
    if (bundle_jobs or (EXISTING_APP and APP_NAME == BUNDLE_APP)) and not ADOPT:
        found.append(f"the app {APP_NAME} and its jobs were deployed by the bundle (databricks bundle deploy), not by this "
                     "installer: " + ("set adopt_app=True to take them over, or choose another app_name"
                                      if not UNINSTALL else "set adopt_app=True to remove them here, "
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
                         + ": uninstall can't roll back or drop it (leave drop_data and rollback_services False)")
    else:
        if foreign and not SECOND_INSTALL:
            found.append("another toolkit install exists under app name " + ", ".join(foreign) + ": set app_name "
                         "to that name to update it, or uninstall it first (to run two side by side, set "
                         "second_install=True, with another schema and folder)")
        for c in clash:
            label = "results schema" if c["kind"] == "results" else "install folder"
            found.append(f"the {label} {RESULTS if c['kind'] == 'results' else FOLDER} is used by the toolkit install of app "
                         f"{c['app']}: choose another {'schema' if c['kind'] == 'results' else 'folder'}")
    for name in active_job_names():
        found.append(f"the job '{name}' has a run in progress: wait for it to finish in Jobs, then run again")
    if not UNINSTALL:
        if MARKER_KIND == "other":
            found.append(f"the install folder {FOLDER} belongs to another toolkit install (marker app {MARKER_APP or '?'}): "
                         "choose another folder")
        elif MARKER_KIND == "missing" and any(c not in TOOLKIT_NAMES for c in folder_children(FOLDER)):
            found.append(f"the install folder {FOLDER} has files that aren't the toolkit's and no toolkit marker, so the "
                         "installer won't touch them: choose an empty folder (folder)")
        try:
            cat = w.catalogs.get(CATALOG)
        except (NotFound, ResourceDoesNotExist):
            cat = None
            found.append(f"results catalog {CATALOG!r} " + ("" if CATALOG_GIVEN else "(the workspace's default catalog) ")
                         + "doesn't exist or you can't see it: set catalog= to a catalog where you can create a schema")
        schema = None
        if cat is not None:
            try:
                schema = w.schemas.get(RESULTS)
            except (NotFound, ResourceDoesNotExist):
                schema = None
            if schema:
                owner_app = re.search(r"\(app: ([a-z0-9_-]+)\)", schema.comment or "")
                if owner_app and owner_app.group(1) != APP_NAME:
                    found.append(f"results schema {RESULTS} belongs to app {owner_app.group(1)}: choose another results schema "
                                 "(schema)")
                elif schema.owner != me and not can_use("schema", RESULTS, {"ALL_PRIVILEGES", "CREATE_TABLE", "MODIFY"}):
                    found.append(f"you can't write to {RESULTS}: ask the owner of the schema ({schema.owner}) to run: GRANT "
                                 f"USE SCHEMA, CREATE TABLE, MODIFY ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `{me}`")
        wh_problem = start_warehouse()
        if wh_problem:
            found.append(wh_problem)
        else:
            missing: dict[str, list[str]] = {}
            for t in SYSTEM_TABLES:
                err = run_sql(f"SELECT 1 FROM {t} LIMIT 1")
                if err:
                    missing.setdefault(t.rsplit(".", 1)[0], []).append(f"{t} ({err[:160]})")
            for schema_name, tables in missing.items():
                found.append("the SQL warehouse can't read " + "; ".join(tables) + " (SELECT on system tables is needed for "
                             "the snapshot and the scans): " + system_table_fix([schema_name], me))
        role_problem = run_as_user_problem(RUN_AS)
        if role_problem:
            found.append(role_problem)
        prev = installed_version(EXISTING_APP)
        note = f"version: {prev or 'unknown (no earlier version recorded)'} -> {TOOLKIT_VERSION}"
        problem = downgrade_problem(prev, TOOLKIT_VERSION, ALLOW_DOWNGRADE)
        if problem:
            found.append(problem)
        if not found and cat is not None and schema is None:  # the probe: create the schema as the last check
            err = run_sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}` COMMENT 'Unity Gateway migration app results "
                          f"(app: {APP_NAME})'")
            if err:
                found.append(f"you can't create {RESULTS} ({err[:200]}). " + create_schema_fix(CATALOG, cat.owner, me))
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
    print("Uninstall keeps:\n- " + "\n- ".join(keep))
    for line in warnings:
        print("WARNING:", line)
    blocked = PROBLEMS + plan_problems
    if ROLLBACK and st["pending"] and not apply_job_ids():
        blocked.append("the apply job of this app is missing, so its services can't be rolled back here: roll them back "
                       "with the command line (see the rollback command above) or restore the apply job")
    if PREVIEW:
        if blocked:
            print("Remove would stop:\n- " + "\n- ".join(blocked))
        print("\nNothing was changed. Call uninstall(preview=False) and run again to remove.")
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

if PROBLEMS:
    raise ValueError("Nothing was changed. Fix these first:\n- " + "\n- ".join(PROBLEMS))
print(f"install: {VERSION_NOTE}")
print(f"The jobs will run as {JOB_IDENTITY}. At the end, the first snapshot starts: it reads account-wide system tables "
      "(legacy endpoints and traffic for every workspace in the account) and writes them to the results schema.")
if RUN_AS:
    print(f"The checks above ran as you ({me}). Service principal {RUN_AS} needs the same access: SELECT on the system "
          "tables, USE and CREATE on the results schema, and USE CATALOG, USE SCHEMA and CREATE SERVICE on the target schema.")

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

# MAGIC %md ## 2. Results schema

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

# COMMAND ----------

# MAGIC %md ## 3. Jobs

# COMMAND ----------

SPECS = job_specs(APP_NAME, FOLDER, RESULTS, WAREHOUSE_ID, SECRET_SCHEMAS, ALLOW_SECRET_READ, DEADLINE, RUN_AS,
                  CENTRAL_WORKSPACES, CENTRAL_SECRET)
print(f"The jobs run as {JOB_IDENTITY}" + ("" if RUN_AS else " (set run_as to change it)"))
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

# Operators live in the results schema, where workspace admins edit them in the app (Settings). The first install adds
# you. The app's service principal reads and edits that table only.
OPS_TABLE = f"`{CATALOG}`.`{SCHEMA}`.{OPERATORS_TABLE}"
spark.sql(operators_table_sql(CATALOG, SCHEMA))
_have = [r["email"] for r in spark.sql(f"SELECT email FROM {OPS_TABLE}").collect()]
# An earlier version kept the operators on the app (OPERATORS). The API doesn't return env values (seen live
# 2026-11-12), so they can't be moved here: the run says to add them again.
_had_env_operators = bool(existing_app is not None and existing_app.active_deployment and any(
    e.name == "OPERATORS" for e in (existing_app.active_deployment.env_vars or [])))
_seed = operators_to_seed(_have, me, IS_SP)
for email in _seed:
    spark.sql(f"INSERT INTO {OPS_TABLE} (email, added_by, added_at) VALUES (:email, :by, current_timestamp())",
              args={"email": email, "by": me})
OPERATOR_LIST = _have or _seed
grant_failed = []
for stmt in operator_grants(CATALOG, SCHEMA, app.service_principal_client_id or "<the app's service principal>"):
    try:
        if not app.service_principal_client_id:
            raise ValueError("the app has no service principal yet")
        spark.sql(stmt)
    except Exception as e:  # noqa: BLE001 (any refusal: the operators stay on the app's settings instead)
        grant_failed.append((stmt, str(e)[:200]))
if _had_env_operators and not _have:
    print("Operators moved to the app: Settings. The operators this app had before the update can't be read back, so "
          f"only {', '.join(_seed) or 'nobody'} is an operator now: a workspace admin adds the others in Settings.")
if grant_failed:
    print("Couldn't give the app access to its operators table, so the operators are set on the app for now, and "
          "Settings in the app can't change them. Ask an owner of the catalog or schema to run:\n  "
          + ";\n  ".join(st for st, _ in grant_failed) + ";\nthen run this installer again. (" + grant_failed[0][1] + ")")

deployment = apps.AppDeployment(
    source_code_path=f"{FILES}/app",
    command=["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
    env_vars=app_env(RESULTS, OPERATOR_LIST if grant_failed else [], TOOLKIT_VERSION, SECRET_SCHEMAS, ALLOW_SECRET_READ,
                     DEADLINE, CENTRAL_WORKSPACES, HUB_WORKSPACE_ID))
print("deploying app...")
d = w.apps.deploy_and_wait(APP_NAME, deployment)
print("deployment:", d.status.state.value if d.status and d.status.state else d.status)

# COMMAND ----------

# The install marker records the version, so the next run can show from -> to and refuse a silent downgrade.
w.workspace.upload(MARKER, io.BytesIO(marker_text(APP_NAME, TOOLKIT_VERSION, RESULTS, FOLDER, me).encode()),
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
target = f"{TARGET_CATALOG}.{TARGET_SCHEMA}"
try:
    w.schemas.get(target)
    target_note = (f"Apply writes model services to {target}. It exists. The apply job runs as {JOB_IDENTITY}: that identity needs "
                   f"USE CATALOG, USE SCHEMA and CREATE SERVICE on it.")
except (NotFound, ResourceDoesNotExist):
    target_note = (f"Apply needs the target schema {target}, and it doesn't exist yet (apply stops until it does). The "
                   "installer doesn't create it. Run this as a catalog admin, or ask one:\n  " + "\n  ".join(target_schema_lines(RUN_AS or me)))
print("App:", app.url)
print(f"Open the app: {app.url}  (or Compute > Apps > {APP_NAME})")
print("First steps: wait for the snapshot (a few minutes), then in the app open Scans and click Start scan.")
print(snapshot_note)
print(f"The weekly snapshot job is paused. To run it every Monday at 06:00 UTC, open Jobs > [{APP_NAME}] Unity Gateway "
      "migration snapshot, and unpause its schedule.")
print(target_note)
print("Unity Catalog secret mapping is off. To turn it on, run this installer again with secret_schemas "
      "set to the catalog.schema that holds the secrets (for example main.secrets), and grant the apply job's identity READ on them.")
print(f"Operators: {', '.join(OPERATOR_LIST) or '(none)'}. "
      + ("Workspace admins add or remove operators in the app: Settings." if not grant_failed else
         "Settings in the app can change them once the grants above are run."))
print(f"Results: {RESULTS}. Jobs run as {JOB_IDENTITY}. Version {TOOLKIT_VERSION}. "
      f"The user guide is in {FILES}/USER_GUIDE.md.")
displayHTML(f"""
<h3>Unity Gateway Migration Toolkit is installed</h3>
<p><b>Open the app:</b> <a href="{app.url}" target="_blank">{app.url}</a> (Compute &gt; Apps &gt; {APP_NAME})</p>
<p>Jobs: {", ".join(f'<a href="{host}/jobs/{i}" target="_blank">{r}</a>' for r, i in JOB_IDS.items())}</p>
<p>The first snapshot reads account-wide system tables (every workspace in the account).</p>
<p>First steps: wait for the snapshot (Overview), then <b>Scans</b> &gt; Start scan. {snapshot_note}</p>
<p>The weekly snapshot job is paused: unpause its schedule in Jobs to run it every Monday.</p>
<p>{target_note}</p>
<p>Operators: {", ".join(OPERATOR_LIST) or "(none)"} (workspace admins change them in the app: Settings). Results: {RESULTS}. Jobs run as {JOB_IDENTITY}. Version {TOOLKIT_VERSION}.</p>
<p>To let others view results, run (replace <code>migration-team</code> with your group):<br>
<code>GRANT USE CATALOG ON CATALOG `{CATALOG}` TO `migration-team`;<br>
GRANT USE SCHEMA, SELECT ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `migration-team`;</code></p>
""")

# COMMAND ----------

# Also return the links as the notebook result, so they're visible when the installer runs as a job.
dbutils.notebook.exit(json.dumps({"app": app.url, "version": TOOLKIT_VERSION,
                                  "jobs": {r: f"{host}/jobs/{i}" for r, i in JOB_IDS.items()}}))
