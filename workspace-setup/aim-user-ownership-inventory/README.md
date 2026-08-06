# AIM User-Ownership Inventory

A **report-only** Databricks notebook that inventories every workspace object owned or
controlled by a given set of users, so that **nothing is lost when those users are
deleted**. It is designed as a follow-on to the Automatic Identity Management (AIM)
migration prep script: run it on the users that prep flags as divergent/failing before
you remove any accounts.

## Project Support

Please note that this project is provided for your exploration only and is not formally
supported by Databricks with Service Level Agreements (SLAs). It is provided AS-IS, and we
do not make any guarantees. Please do not submit a support ticket relating to any issues
arising from the use of this project.

## Background: why this exists

When you enable [Automatic Identity Management (AIM)](https://docs.databricks.com/aws/en/admin/users-groups/automatic-identity-management/),
Databricks matches each identity to Microsoft Entra ID using the Entra **Object ID**. The
[migration prep script](https://docs.databricks.com/aws/en/admin/users-groups/automatic-identity-management/migrate-to-aim#prepare-for-migration)
produces a set of result files, including `idp_divergence_users.csv`, listing users whose
Databricks identity diverges from Entra or cannot be matched.

A very common outcome is that many of the divergent/failing users are **former employees**
whose accounts should be deleted. Before deleting them, admins need to answer a practical
question:

> *Do any of these users own assets that are still in use, and would we lose anything by
> deleting the account?*

Deleting a user in Databricks removes their home folder (`/Users/<email>/`) and everything
in it, and can break jobs, dashboards, and alerts that depend on that user. This notebook
gives you a clear, per-user inventory so you can **transfer anything that must survive
before you delete the account**.

## When to use this

- **After running the AIM migration prep script**, when you have `idp_divergence_users.csv`
  (or any list of users) and need to clean up former-employee accounts.
- More generally, **any time you offboard users** and want to confirm what they own before
  deletion.

You do **not** need AIM to be enabled to run this. It only reads the current workspace.

## What it reports (per user)

- **Home-folder contents** — notebooks, files, and folders under `/Users/<email>/`. **This
  is the most important category**, because a user's home folder is deleted along with the
  account. Anything here that must survive has to be moved or transferred first.
- **Jobs** — `creator_user_name` and `run_as`. A job whose `run_as` points at a deleted
  user will stop running.
- **DBSQL queries and alerts** — owner.
- **Lakeview (AI/BI) dashboards** — `CAN_MANAGE` holder (see note on ownership below).
- **DLT / Lakeflow pipelines** — creator.
- **Clusters and cluster policies** — creator / single-user.
- **SQL warehouses** — creator.
- **Registered models and MLflow experiments** — owner / `CAN_MANAGE`.
- **Repos** — path under `/Repos/<user>/`.
- **Personal access tokens** — `created_by_username` (the token becomes invalid on
  deletion).

Output is a single table and a CSV, one row per owned object.

## Important scope and design notes

- **This notebook is workspace-scoped.** It inventories objects in the single workspace
  where you run it. Under identity federation, user *identities* are shared across your
  account, but the *objects* (home folders, jobs, queries, dashboards, and so on) live in a
  specific workspace. **If more than one workspace is in scope, run the notebook once in
  each workspace** with the same user list. The output includes `workspace_id` and
  `workspace_host` columns so results from multiple workspaces combine cleanly.
- **It is report-only.** It never transfers, deletes, or modifies anything. Transferring
  ownership is a deliberate, manual step you take after reviewing the output.
- **It does not cover Unity Catalog objects** (catalogs, schemas, tables, volumes, UC
  models). Those are governed at the **metastore** level, not per workspace, and require a
  metastore admin to review and transfer (`ALTER <object> OWNER TO ...`). Run a separate UC
  ownership check for those.
- **On the word "ownership":** workspace objects such as notebooks, files, dashboards, and
  experiments do **not** expose an `IS_OWNER` ACL level — their ACLs top out at
  `CAN_MANAGE`. Notebook/file "ownership" is therefore determined by the **home-folder
  path**, and for dashboards/experiments the notebook reports `CAN_MANAGE` holders as the
  closest available control signal.

## Prerequisites

- You must be a **workspace administrator** in the workspace you are scanning (needed to
  list objects and read their permissions across the workspace).
- Compute to run the notebook — **Serverless** is sufficient; no special configuration is
  required. All operations use the Databricks REST APIs via the
  [Databricks SDK for Python](https://databricks-sdk-py.readthedocs.io/), which is
  preinstalled on Databricks Runtime.

## How to use

1. **Import the notebook** into your workspace: `Workspace > Import > File` and select
   `user_owned_objects_inventory.py`.
2. **Provide the users** in the first (Configuration) cell, using either:
   - `USER_IDS` — a list of Databricks numeric user IDs (the `id` column from the prep
     script's `idp_divergence_users.csv`) and/or emails, or
   - `FAILURES_CSV_PATH` — a path to the uploaded `idp_divergence_users.csv` (a UC Volume
     or workspace path); the notebook reads the `id` column for you.
3. Optionally set `OUTPUT_VOLUME_PATH` to a UC Volume so the CSV persists and is shareable.
4. **Run all.** Review the summary, the interactive table, and the exported CSV.

### Example configuration

```python
# Option A: paste IDs from the prep script's idp_divergence_users.csv "id" column
USER_IDS = ["8714258940588932", "70507760680636"]

# Option B: let the notebook read the ids from the CSV directly
FAILURES_CSV_PATH = "/Volumes/main/default/aim_offboarding/idp_divergence_users.csv"
```

The notebook resolves each ID to its email via SCIM, then scans. Any input that cannot be
resolved (for example, an already-deleted account) is listed separately rather than
silently dropped.

## Recommended offboarding workflow

1. **Inventory** the departing users with this notebook (once per in-scope workspace).
2. **Review** the output. For each object, decide: transfer, or safe to drop.
3. **Transfer ownership** of anything that must survive, *before* deleting the user:
   - Most objects: Permissions API —
     `PUT /api/2.0/permissions/{type}/{id}` with an access control list granting the new
     owner `IS_OWNER` (or `CAN_MANAGE` where `IS_OWNER` is not supported).
   - Dashboards: also assignable via the dashboard **Share** UI (workspace admin).
   - Jobs whose `run_as` is the departing user: repoint `run_as` to a service principal or
     active owner, or the job will stop running.
4. **Unity Catalog** (separate check): as a metastore admin, review and transfer UC objects
   with `ALTER <CATALOG|SCHEMA|TABLE|...> OWNER TO ...`.
5. **Re-run** this notebook to confirm the user owns nothing, then delete the account.

## Security and data

- The notebook reads only metadata (object names, IDs, paths, owner/creator fields, ACLs).
  It reads no data inside tables or files.
- It writes no credentials and requires none beyond the running admin's own workspace
  authentication.
- It performs no mutating operations.
