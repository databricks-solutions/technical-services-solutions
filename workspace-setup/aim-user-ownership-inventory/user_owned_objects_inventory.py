# Databricks notebook source
# MAGIC %md
# MAGIC # User-Owned Workspace Objects Inventory (Report-Only)
# MAGIC
# MAGIC **Purpose:** Before deleting users who have left the company, find every workspace
# MAGIC object each of them **owns or controls**, so nothing is orphaned or lost. This notebook
# MAGIC is **read-only** — it never changes, deletes, or reassigns anything. It only reports.
# MAGIC
# MAGIC **Who runs it:** A **workspace admin** (needs permission to list objects and read their
# MAGIC permissions). Run it once per workspace you want to check.
# MAGIC
# MAGIC **What it finds, per user:**
# MAGIC - **Home-folder contents (notebooks / files / folders)** — everything under
# MAGIC   `/Users/<email>/`. **This is the most important category: this content is deleted
# MAGIC   along with the user account**, so anything here that must survive has to be moved out
# MAGIC   or transferred first.
# MAGIC - **Jobs** — `creator_user_name` and `run_as` (a job whose `run_as` points at a deleted user will stop running)
# MAGIC - **DBSQL queries & alerts** — owner
# MAGIC - **Lakeview (AI/BI) dashboards** — `CAN_MANAGE` on the ACL (see note below)
# MAGIC - **DLT / Lakeflow pipelines** — `creator_user_name`
# MAGIC - **Clusters & cluster policies** — creator / single-user
# MAGIC - **SQL warehouses** — creator
# MAGIC - **Registered models & MLflow experiments** — owner / `CAN_MANAGE`
# MAGIC - **Repos** — path under `/Repos/<user>/`
# MAGIC - **Personal access tokens** — `created_by_username`
# MAGIC
# MAGIC **Note on "ownership" signal:** Workspace objects (notebooks, files, dashboards,
# MAGIC experiments) do **not** expose an `IS_OWNER` ACL level — their ACLs only go up to
# MAGIC `CAN_MANAGE`. Notebook/file ownership is instead defined by the **home-folder path**.
# MAGIC For dashboards/experiments this notebook reports `CAN_MANAGE` holders as the closest
# MAGIC available control signal, so review those rows as "manages" rather than strict "owns".
# MAGIC
# MAGIC **What it does NOT cover:** Unity Catalog objects (catalogs, schemas, tables, UC models,
# MAGIC volumes). Those are **metastore-scoped**, not workspace-scoped, and their ownership is
# MAGIC managed separately (metastore admin, `SHOW GRANTS` / `ALTER ... OWNER TO`). Run a
# MAGIC separate UC check for those.
# MAGIC
# MAGIC **How to use:** Provide the departing users by their **Databricks numeric user ID**
# MAGIC (the `id` column from the prep script's `idp_divergence_users.csv`) in `USER_IDS`, or
# MAGIC point `FAILURES_CSV_PATH` at the uploaded CSV to load them automatically. Emails work
# MAGIC too. The notebook resolves each ID to its email via SCIM, then **Run all**. Review the
# MAGIC final table / exported CSV. For anything that must survive the user's deletion,
# MAGIC transfer ownership (Permissions API, or the object's UI) **before** deleting the account.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Configuration

# COMMAND ----------

# Users to inventory (the departing / ex-employee accounts). You can identify them by
# either their Databricks numeric user ID or their email — mix freely.
#
# The prep script's idp_divergence_users.csv emits the numeric "id" column; paste those
# here directly (as strings or ints). Emails also work if you have them.
#   USER_IDS = ["8714258940588932", "70507760680636"]        # from the CSV "id" column
#   USER_IDS = ["user1@example.com"]                        # emails are fine too
USER_IDS = [
    "8714258940588932",
]

# Convenience: load IDs straight from the prep script's CSV instead of pasting them.
# Point this at the uploaded idp_divergence_users.csv (UC Volume or workspace path).
# When set, its "id" column is used and USER_IDS above is ignored.
FAILURES_CSV_PATH = None  # e.g. "/Volumes/main/default/aim_offboarding/idp_divergence_users.csv"

# Inventory each user's home folder (/Users/<email>/). This is the critical category:
# home-folder contents are DELETED with the user account. Strongly recommended to keep True.
SCAN_HOME_FOLDER = True

# For ACL-based objects (dashboards, experiments), workspace ACLs top out at CAN_MANAGE —
# there is no IS_OWNER level for these. We therefore report CAN_MANAGE holders as the
# closest control signal. Set False to skip these (fewer, noisier rows).
INCLUDE_CAN_MANAGE = True

# Where to write the CSV. A UC Volume path is recommended so it persists and is shareable.
# Leave as None to write to the driver's local /tmp and display inline only.
OUTPUT_VOLUME_PATH = None  # e.g. "/Volumes/main/default/aim_offboarding"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Setup

# COMMAND ----------

from databricks.sdk import WorkspaceClient
import pandas as pd
from datetime import datetime, timezone

w = WorkspaceClient()
HOST = w.config.host.rstrip("/") if w.config.host else ""

# Identify THIS workspace so results are unambiguous when you run the notebook in several
# workspaces and concatenate the CSVs. (Identities are shared account-wide under federation,
# but the objects below are per-workspace — this column records which workspace each came from.)
try:
    WORKSPACE_ID = str(w.get_workspace_id())
except Exception:
    WORKSPACE_ID = ""
WORKSPACE_HOST = HOST
print(f"Workspace: {WORKSPACE_HOST} (id={WORKSPACE_ID})")

# --- Build the raw input list (from CSV if provided, else from USER_IDS) ---
raw_inputs = []
if FAILURES_CSV_PATH:
    # Read the prep script's CSV and pull its "id" column.
    read_path = FAILURES_CSV_PATH
    if read_path.startswith("/Volumes") or read_path.startswith("/Workspace"):
        # pandas can read UC Volume / workspace files directly on serverless & clusters.
        pass
    _csv = pd.read_csv(read_path, dtype=str)
    id_col = next((c for c in _csv.columns if c.strip().lower() == "id"), None)
    if id_col is None:
        raise ValueError(f"No 'id' column found in {read_path}. Columns: {list(_csv.columns)}")
    raw_inputs = [v for v in _csv[id_col].dropna().tolist() if str(v).strip()]
    print(f"Loaded {len(raw_inputs)} id(s) from {read_path}")
else:
    raw_inputs = [str(x).strip() for x in USER_IDS if str(x).strip()]

# --- Resolve each input (numeric ID or email) to a canonical email via SCIM ---
# Object owner/creator fields and home-folder paths key off the email (userName), so we
# resolve everything to email up front. Numeric IDs are looked up directly; emails are
# validated (and normalized) via a filter query.
def _resolve_to_email(token):
    t = str(token).strip()
    try:
        if t.isdigit():
            u = w.users.get(id=t)
            return (u.user_name, None)
        else:
            # treat as email/userName — validate it exists
            matches = list(w.users.list(filter=f'userName eq "{t}"', count=1))
            if matches:
                return (matches[0].user_name, None)
            return (t.lower(), "not found in directory (may already be deleted)")
    except Exception as e:
        return (None, f"{type(e).__name__}: {e}")

TARGETS = set()          # canonical lowercased emails to match against
RESOLVED = []            # (input_token, email, note) for the report
UNRESOLVED = []          # inputs we could not map to an email
for token in raw_inputs:
    email, note = _resolve_to_email(token)
    if email:
        TARGETS.add(email.strip().lower())
        RESOLVED.append((token, email, note or ""))
    else:
        UNRESOLVED.append((token, note))

print(f"Inventorying {len(TARGETS)} user(s):")
for tok, email, note in sorted(RESOLVED, key=lambda r: r[1]):
    suffix = f"  <-- {note}" if note else ""
    print(f"  - {tok} => {email}{suffix}")
if UNRESOLVED:
    print(f"\n{len(UNRESOLVED)} input(s) could NOT be resolved to an email (skipped):")
    for tok, note in UNRESOLVED:
        print(f"  - {tok}: {note}")
    print("  A deleted account has no home folder to scan, but it may still own objects "
          "(creator fields persist). Consider checking these IDs before this run if possible.")

findings = []  # each: dict(user_email, object_type, ownership_signal, object_id, object_name, object_path, url, notes)


def add(user_email, object_type, signal, object_id="", name="", path="", url="", notes=""):
    findings.append({
        "workspace_id": WORKSPACE_ID,
        "workspace_host": WORKSPACE_HOST,
        "user_email": user_email,
        "object_type": object_type,
        "ownership_signal": signal,
        "object_id": str(object_id),
        "object_name": name or "",
        "object_path": path or "",
        "url": url,
        "notes": notes,
    })


def match(value):
    """Return the target email (lowercased) if value matches one of our targets, else None."""
    if not value:
        return None
    v = str(value).strip().lower()
    return v if v in TARGETS else None


def owner_from_acl(object_type_api, object_id):
    """Return list of (target_email, permission_level) for target users holding IS_OWNER,
    or CAN_MANAGE when INCLUDE_CAN_MANAGE is set, on the given object.

    Note: workspace objects (notebooks, files, dashboards, experiments) do NOT expose an
    IS_OWNER level — their ACLs top out at CAN_MANAGE. So for those, CAN_MANAGE is the
    strongest available control signal. Home-folder ownership is handled separately by path."""
    hits = []
    try:
        perms = w.permissions.get(request_object_type=object_type_api, request_object_id=str(object_id))
    except Exception:
        return hits
    for acl in (perms.access_control_list or []):
        tgt = match(getattr(acl, "user_name", None))
        if not tgt:
            continue
        for p in (acl.all_permissions or []):
            lvl = getattr(p.permission_level, "value", str(p.permission_level))
            # Skip permissions inherited from a parent/group — only direct grants indicate control.
            if getattr(p, "inherited", False):
                continue
            if lvl == "IS_OWNER" or (INCLUDE_CAN_MANAGE and lvl == "CAN_MANAGE"):
                hits.append((tgt, lvl))
    return hits


def safe(section):
    """Decorator: wrap a scan section so that calling it runs with error handling —
    one failing API won't abort the whole inventory. Returns a callable (does NOT run
    the scan at decoration time)."""
    def deco(fn):
        def wrapped():
            try:
                fn()
                print(f"  [ok] {section}")
            except Exception as e:
                print(f"  [skip] {section}: {type(e).__name__}: {e}")
        return wrapped
    return deco

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Scan compute, jobs, and SQL objects (fast — ownership/creator fields)

# COMMAND ----------

print("Scanning...")

@safe("Jobs (creator + run_as)")
def _jobs():
    for j in w.jobs.list(expand_tasks=False):
        jid = j.job_id
        s = j.settings
        name = getattr(s, "name", "") if s else ""
        url = f"{HOST}/jobs/{jid}"
        # creator
        tgt = match(getattr(j, "creator_user_name", None))
        if tgt:
            add(tgt, "job", "creator_user_name", jid, name, url=url)
        # run_as (critical: a job run_as a deleted user will fail)
        run_as = getattr(s, "run_as", None) if s else None
        run_as_user = getattr(run_as, "user_name", None) if run_as else None
        tgt2 = match(run_as_user)
        if tgt2:
            add(tgt2, "job", "run_as (job will fail if user deleted)", jid, name, url=url,
                notes="run_as points at this user")


@safe("Clusters (creator + single-user)")
def _clusters():
    for c in w.clusters.list():
        cid = c.cluster_id
        name = getattr(c, "cluster_name", "")
        url = f"{HOST}/#setting/clusters/{cid}"
        tgt = match(getattr(c, "creator_user_name", None))
        if tgt:
            add(tgt, "cluster", "creator_user_name", cid, name, url=url)
        tgt2 = match(getattr(c, "single_user_name", None))
        if tgt2:
            add(tgt2, "cluster", "single_user_name", cid, name, url=url,
                notes="single-user (dedicated) cluster")


@safe("Cluster policies (creator)")
def _policies():
    for p in w.cluster_policies.list():
        tgt = match(getattr(p, "creator_user_name", None))
        if tgt:
            add(tgt, "cluster_policy", "creator_user_name",
                getattr(p, "policy_id", ""), getattr(p, "name", ""))


@safe("SQL warehouses (creator)")
def _warehouses():
    for wh in w.warehouses.list():
        tgt = match(getattr(wh, "creator_name", None))
        if tgt:
            add(tgt, "sql_warehouse", "creator_name", getattr(wh, "id", ""),
                getattr(wh, "name", ""), url=f"{HOST}/sql/warehouses/{getattr(wh,'id','')}")


@safe("DLT / Lakeflow pipelines (creator)")
def _pipelines():
    for p in w.pipelines.list_pipelines():
        tgt = match(getattr(p, "creator_user_name", None))
        if tgt:
            add(tgt, "pipeline", "creator_user_name", getattr(p, "pipeline_id", ""),
                getattr(p, "name", ""),
                url=f"{HOST}/pipelines/{getattr(p,'pipeline_id','')}")


@safe("DBSQL queries (owner)")
def _queries():
    for q in w.queries.list():
        owner = getattr(q, "owner_user_name", None)
        tgt = match(owner)
        if tgt:
            add(tgt, "dbsql_query", "owner_user_name", getattr(q, "id", ""),
                getattr(q, "display_name", "") or getattr(q, "name", ""))


@safe("DBSQL alerts (owner)")
def _alerts():
    for a in w.alerts.list():
        tgt = match(getattr(a, "owner_user_name", None))
        if tgt:
            add(tgt, "dbsql_alert", "owner_user_name", getattr(a, "id", ""),
                getattr(a, "display_name", ""))


@safe("Personal access tokens (created_by)")
def _tokens():
    for t in w.token_management.list():
        tgt = match(getattr(t, "created_by_username", None))
        if tgt:
            add(tgt, "pat_token", "created_by_username", getattr(t, "token_id", ""),
                getattr(t, "comment", "") or "(no comment)",
                notes="token becomes invalid when user is deleted")

_jobs(); _clusters(); _policies(); _warehouses(); _pipelines(); _queries(); _alerts(); _tokens()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Scan Lakeview dashboards, models, experiments, repos

# COMMAND ----------

@safe("Lakeview (AI/BI) dashboards (IS_OWNER)")
def _dashboards():
    for d in w.lakeview.list():
        did = getattr(d, "dashboard_id", "")
        name = getattr(d, "display_name", "")
        url = f"{HOST}/dashboardsv3/{did}"
        for tgt, lvl in owner_from_acl("dashboards", did):
            add(tgt, "lakeview_dashboard", f"ACL {lvl}", did, name, url=url)


@safe("Unity Catalog registered models (owner)")
def _uc_models():
    # UC models carry an explicit owner. (Metastore-scoped, but listed here for convenience.)
    for m in w.registered_models.list():
        tgt = match(getattr(m, "owner", None))
        if tgt:
            add(tgt, "uc_registered_model", "owner", getattr(m, "full_name", ""),
                getattr(m, "name", ""),
                notes="Unity Catalog object — transfer via ALTER ... OWNER TO (metastore)")


@safe("Legacy MLflow registered models (IS_OWNER)")
def _legacy_models():
    # Workspace model registry models use the Permissions API (registered-models).
    for m in w.model_registry.list_models():
        name = getattr(m, "name", "")
        # permission id for registered-models is the model's id; resolve via get.
        try:
            got = w.model_registry.get_model(name=name)
            mid = getattr(getattr(got, "registered_model_databricks", None), "id", None)
        except Exception:
            mid = None
        if not mid:
            continue
        for tgt, lvl in owner_from_acl("registered-models", mid):
            add(tgt, "mlflow_model", f"ACL {lvl}", mid, name)


@safe("MLflow experiments (IS_OWNER)")
def _experiments():
    for ex in w.experiments.list_experiments():
        eid = getattr(ex, "experiment_id", "")
        name = getattr(ex, "name", "")
        for tgt, lvl in owner_from_acl("experiments", eid):
            add(tgt, "mlflow_experiment", f"ACL {lvl}", eid, name)


@safe("Repos (path under /Repos/<user>)")
def _repos():
    for r in w.repos.list():
        path = getattr(r, "path", "") or ""
        # /Repos/<email>/<repo>
        parts = path.split("/")
        owner = parts[2] if len(parts) > 2 and parts[1] == "Repos" else None
        tgt = match(owner)
        if tgt:
            add(tgt, "repo", "path /Repos/<user>", getattr(r, "id", ""),
                getattr(r, "url", ""), path=path)

_dashboards(); _uc_models(); _legacy_models(); _experiments(); _repos()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Home-folder inventory — notebooks, files, folders under `/Users/<email>/`
# MAGIC
# MAGIC **This is the highest-priority category.** A user's home folder and everything in it
# MAGIC is **deleted when the account is deleted**. Ownership here is defined by the *path*
# MAGIC (`/Users/<email>/...`), not by an ACL — workspace objects have no `IS_OWNER` level.
# MAGIC So we enumerate the tree directly. Controlled by `SCAN_HOME_FOLDER`.

# COMMAND ----------

if SCAN_HOME_FOLDER:
    from databricks.sdk.service.workspace import ObjectType

    def walk_home(user_email, path, counter):
        try:
            children = list(w.workspace.list(path))
        except Exception as e:
            print(f"  [skip dir] {path}: {e}")
            return
        for obj in children:
            ot = obj.object_type
            opath = getattr(obj, "path", "")
            oid = getattr(obj, "object_id", "")
            if ot in (ObjectType.NOTEBOOK, ObjectType.FILE, ObjectType.DIRECTORY):
                counter[0] += 1
                add(user_email, ot.value.lower(), "in home folder (deleted with user)",
                    oid, opath.split("/")[-1], path=opath, url=f"{HOST}/#workspace{opath}",
                    notes="lost on user deletion unless moved/exported")
            if ot == ObjectType.DIRECTORY:
                walk_home(user_email, opath, counter)

    for email in sorted(TARGETS):
        home = f"/Users/{email}"
        # Confirm the home folder exists before walking.
        try:
            w.workspace.get_status(home)
        except Exception:
            print(f"  [no home folder] {home}")
            continue
        counter = [0]
        walk_home(email, home, counter)
        print(f"  {email}: {counter[0]} object(s) under {home}")
else:
    print("SCAN_HOME_FOLDER = False — skipping home-folder inventory (NOT recommended).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Results

# COMMAND ----------

df = pd.DataFrame(findings, columns=[
    "workspace_id", "workspace_host", "user_email", "object_type", "ownership_signal",
    "object_id", "object_name", "object_path", "url", "notes",
])

scan_ts = datetime.now(timezone.utc).isoformat()

print(f"Scan timestamp (UTC): {scan_ts}")
print(f"Total owned objects found: {len(df)}\n")

if not df.empty:
    print("Per-user summary:")
    print(df.groupby("user_email").size().sort_values(ascending=False).to_string())
    print("\nBy object type:")
    print(df.groupby("object_type").size().sort_values(ascending=False).to_string())

    # Users from the target list that own NOTHING found — safe to delete (workspace-side).
    owned_users = set(df["user_email"].unique())
    clean = sorted(TARGETS - owned_users)
    print(f"\nUsers with NO workspace objects found ({len(clean)}) — "
          f"workspace-side safe to delete (still verify Unity Catalog separately):")
    for u in clean:
        print(f"  - {u}")
else:
    print("No owned objects found for any listed user (workspace-side). "
          "Still verify Unity Catalog ownership separately.")

# COMMAND ----------

# Display the full inventory as an interactive, sortable/filterable table.
display(spark.createDataFrame(df) if not df.empty else spark.createDataFrame([], "user_email string"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Export CSV

# COMMAND ----------

local_csv = "/tmp/user_owned_objects_inventory.csv"
df.to_csv(local_csv, index=False)
print(f"Wrote: {local_csv}")

if OUTPUT_VOLUME_PATH:
    import os
    os.makedirs(OUTPUT_VOLUME_PATH, exist_ok=True)
    vol_csv = f"{OUTPUT_VOLUME_PATH.rstrip('/')}/user_owned_objects_inventory.csv"
    dbutils.fs.cp(f"file:{local_csv}", vol_csv)
    print(f"Copied to volume: {vol_csv}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Next steps (manual, deliberate)
# MAGIC
# MAGIC 1. **Review** the table above. For each row, decide: transfer, or safe to drop.
# MAGIC 2. **Transfer ownership** of anything that must survive, *before* deleting the user:
# MAGIC    - Most objects: Permissions API — `PUT /api/2.0/permissions/{type}/{id}` with
# MAGIC      `{"access_control_list":[{"user_name":"new.owner@example.com","permission_level":"IS_OWNER"}]}`
# MAGIC    - Dashboards: also assignable via the dashboard **Share** UI (workspace admin).
# MAGIC    - Jobs with `run_as` on the departing user: update `run_as` to a service principal
# MAGIC      or active owner, or the job **will stop running** on deletion.
# MAGIC 3. **Unity Catalog** (separate check): as a metastore admin, review UC objects owned by
# MAGIC    the user and use `ALTER <CATALOG|SCHEMA|TABLE|...> OWNER TO ...`.
# MAGIC 4. **Re-run this notebook** to confirm the user owns nothing, then delete the account.
# MAGIC
# MAGIC > This notebook is intentionally **report-only**. It performs no transfers or deletions.
