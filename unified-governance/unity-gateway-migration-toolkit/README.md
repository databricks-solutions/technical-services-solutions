# Unity Gateway Migration Toolkit (prototype, v0.11.0)

Moves legacy model serving endpoints (v1, and v2 workspace-bound endpoints) to Unity Gateway. Planning and scans only read. Writes happen only when you start them: apply, rollback, usage tracking, pause and resume, test calls, and snapshots.

> Prototype from Databricks Shared Technical Services, provided as is. Review every result before you act on it.

**Deadline:** every legacy endpoint stops accepting requests on **March 30, 2027** (confirmed as of November 1, 2026).

## Quick start (about 5 minutes, inside the workspace)

1. In the workspace, open your home folder and choose **Import**, then **URL**, and paste:
   `https://raw.githubusercontent.com/databricks-solutions/technical-services-solutions/main/unified-governance/unity-gateway-migration-toolkit/INSTALL_unity_gateway_migration_toolkit_0_11_0.py`
   (No internet access from the workspace? Download `unity-gateway-migration-toolkit.zip` from the [release page](https://github.com/databricks-solutions/technical-services-solutions/releases/tag/unity-gateway-migration-toolkit-latest), unzip it, and import that file from the zip's top folder.)
2. Open the notebook. The settings cell holds one call, like [dbdemos](https://github.com/databricks-demos/dbdemos):
   ```python
   install(
       catalog=None,    # results catalog; None = the existing install's, else the workspace's default catalog
       warehouse=None,  # SQL warehouse name or ID; None = the existing install's, else the running one
   )
   ```
   Leave it as is for the defaults, or set a value (`catalog="main"`). `help(install)` lists the other settings.
3. Click **Run all**. The last cell prints the app link.
4. Open **Compute > Apps > ug-migration-toolkit**.
5. Work through the tabs in order: **Overview** (refresh the snapshot), **Scans** (scan this workspace), **Apply** (dry run, then execute), **Verify & cut over** (a status strip, then traffic, tracking, pause, test call and the Enforce checklist, one step at a time). The target schema for new services is chosen in Apply.

Run the installer as a workspace admin with system table access. By default the jobs run as you, so operators who start them from the app act with your permissions. You are the first operator; workspace admins add others in the app (**Settings**). For anything beyond a trial, set `run_as=` to a service principal's application ID, with only the access the toolkit needs ([Who the jobs run as](USER_GUIDE.md#1-install)). The first snapshot reads account-wide system tables, so it covers every workspace in the account. Many workspaces? One install can also scan the others ([Central mode](USER_GUIDE.md#central-mode-optional-one-install-for-many-workspaces), optional). If the installer says the target schema `ai_gateway.migrated` is missing, create it first. The installer prints the SQL.

![Account overview with headline counts, the deadline countdown, a trend chart and workspaces by wave](docs/screenshots/overview.png)

*The account overview after a snapshot: counts, legacy tokens, v2 calls already failing, days to the deadline, the trend, and the migration waves.*

## What it does

- Inventories every legacy endpoint, v1 and v2, with its traffic (requests, and tokens for sizing) and callers, for one workspace or the whole account.
- Finds the code that calls legacy endpoints and proposes each line change. It never edits your code.
- Creates Unity Gateway services for external model and Provisioned Throughput endpoints when you ask, with rollback.
- Runs the verify and cut-over steps and says whether a workspace is ready to enforce.

Job tags: the toolkit's jobs carry `tool = ug-migration-toolkit`, `Project = unity-gateway-migration-toolkit`, `app` and `role`. They are labels only.

## Documentation

- [USER_GUIDE.md](USER_GUIDE.md): the full journey, from install to uninstall, then reference, troubleshooting, limitations and FAQ.
- [HOW_TO_READ.md](HOW_TO_READ.md): what each output file contains.

## Command line and bundle

The planning and apply code also runs as Python scripts (`ug_migration_planner.py`, `ug_migration_account.py`, `ug_migration_apply.py`) and as a Declarative Automation Bundle (`databricks.yml`). See [section 7](USER_GUIDE.md#7-command-line-and-bundle). The verify and cut-over steps run from the app only.
