# Install the Unity Gateway Migration Toolkit

One notebook installs everything inside your workspace in about 5 minutes. No CLI, Git or local setup.

## What you need

| Need | Why | If it's missing |
|---|---|---|
| Permission to create Databricks Apps and jobs (usually a workspace admin) | The installer creates an app and three jobs | Ask a workspace admin to run the installer |
| A catalog where you have `USE CATALOG` and `CREATE SCHEMA` | The toolkit creates its two schemas there (below) | The checklist prints the `GRANT` to send the catalog owner |
| `CAN USE` on a SQL warehouse | The app and jobs query through it | Ask a workspace admin for one |
| `USE CATALOG` on `system`, and `SELECT` on four system tables: `system.serving.endpoint_usage`, `system.serving.served_entities`, `system.ai_gateway.usage`, `system.access.workspaces_latest` | Legacy endpoints and their traffic come from them | The checklist prints the `GRANT` to send an account admin |

## What it creates

| What | Name (defaults) | Notes |
|---|---|---|
| Results schema | `<catalog>.ug_migration` | Scan results and history. Keep it to the migration team: scans store matched code lines |
| Schema for new model services | `<catalog>.ug_migrated` | Empty until you run Apply. The service names end up in your callers' code (`<catalog>.ug_migrated.<service>`), so pick the schema you want to keep. Already have one? Enter it in widget 3 |
| Toolkit files | `/Workspace/Users/<you>/ug-migration-toolkit` | Replaced on every update |
| Three jobs | `[ug-migration-toolkit] Unity Gateway migration snapshot`, `workspace scan`, `apply` | Started from the app. Tagged `Project = unity-gateway-migration-toolkit`. The weekly snapshot is paused |
| The app | `ug-migration-toolkit` (Compute > Apps) | Where you work: Overview, Scans, Apply, Verify & cut over. Only operators (default: you) can start jobs in it; others can view |

The install never changes your endpoints or code. Changes happen later, only when you start them in the app.

## Install

1. Download `unity-gateway-migration-toolkit.zip` from the [release page](https://github.com/databricks-solutions/technical-services-solutions/releases/tag/unity-gateway-migration-toolkit-latest) and unzip it. In the workspace, open your home folder, choose **Import**, and import `INSTALL_unity_gateway_migration_toolkit_0_11_0.py` from the zip's top folder.
2. Open the notebook and click **Run all**. The first run is a **preview**: it adds three widgets at the top, prefilled with this workspace's default catalog and a running SQL warehouse, runs every check, and prints what it would create. It changes nothing.
3. Check the widgets, and change any you want:

   | Widget | What it is |
   |---|---|
   | **1. Catalog** | Where the toolkit creates its two schemas |
   | **2. SQL warehouse** | What the app and jobs query through |
   | **3. Schema for new model services** | Blank: `<catalog>.ug_migrated` is created for you. Or enter `catalog.schema` of a schema you already have, or want created |

4. Click **Run all** again to install (about 5 minutes).

The checklist (shortened here) looks like this, in the preview and again in the install:

```
Checklist:
  [OK  ] Databricks Apps: you can create apps
  [OK  ] Catalog: main (the results schema goes here)
  [OK  ] SQL warehouse: Serverless Starter Warehouse (0123456789abcdef) is running
  [FIX ] the SQL warehouse can't read system.serving.endpoint_usage (the snapshot and scans need SELECT on it). Ask an account admin to run: GRANT ...
  [OK  ] Schema for new model services: main.ug_migrated doesn't exist: it will be created
```

- **FIX** stops the install. Nothing is created or changed (a stopped SQL warehouse may have been started for the checks). Fix each FIX item (the message has the exact `GRANT` or what to set), then Run all again. In the preview it ends with "Preview: nothing was changed"; on an install run, the cell ends with a red "Nothing was changed" error, which is expected.
- **NOTE** doesn't stop it. For example, if the schema for new model services can't be created, the install goes on, scans work, and Apply waits until the schema exists. The SQL to create it is printed.

When it finishes, it prints the app link. Open the app, wait a few minutes for the first snapshot, then go to **Scans** and click **Start scan**.

## Optional settings

Below the widgets, a cell titled **Optional settings** holds everything else, each with a comment. Most installs leave it as is. To change a setting, edit its value in that cell and click Run all. Blank (`""`) keeps the default, or what the install already in the workspace uses; `"none"` clears a setting.

| Setting | Use it for |
|---|---|
| `app_name` | A second install. An older install (`unity-gateway-migration` from 0.8, `ug-migration` from 0.7) is found without it when it's the only one |
| `operators` | Who can start jobs in the app. Default: you |
| `run_as` | A shared install: the jobs run as this service principal (its application ID). You need its **Service principal: User** role |
| `create_target` | `"no"` if you'll create schema 3 yourself (the SQL is printed). Default: yes |
| `results_schema`, `install_folder` | Other locations |
| `secret_schemas`, `allow_secret_read` | Secret mapping in Apply |
| `deadline` | A date other than March 30, 2027 |
| `central_workspaces`, `central_secret` | One install that also manages other workspaces |
| `adopt_app`, `allow_downgrade`, `second_install` | Special cases. The checklist tells you when you need one |

A job that runs the installer can pass the same names as parameters (`app_name`, `operators`, ...), and the widgets as `01_catalog`, `02_warehouse` and `03_target`. A job run never previews.

## Update

Import the newer installer and click **Run all**. With an install already in the workspace, the widgets start at "keep the current one" and every setting is kept: catalog and schemas, warehouse, operators, the jobs' service principal, central mode and secret mapping. The first run previews what it would change; the next Run all updates. The run lists what it kept.

**Updating from 0.10 or earlier:** those installs didn't record their operators, and Databricks doesn't return them, so the first update asks for them once (a FIX). Enter them in `operators` in the Optional settings cell (your email alone is fine), then Run all again. Later updates keep them.

The [user guide](USER_GUIDE.md#installer-widgets) lists the widgets and settings, and [Troubleshooting](USER_GUIDE.md#9-troubleshooting) maps each installer message to its fix.

## Uninstall

Import `UNINSTALL_unity_gateway_migration_toolkit_0_11_0.py` from the same zip. Run all with **1. Action** = `preview` first: it lists what would be removed and kept, and changes nothing. Then set **1. Action** to `remove` and Run all again. Model services created by Apply stay unless you set **3. Roll back services** to `yes`. See [Uninstall and cleanup](USER_GUIDE.md#6-uninstall-and-cleanup).
