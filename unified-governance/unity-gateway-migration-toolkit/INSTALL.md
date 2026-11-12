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
2. Open the notebook and click **Run all** (about 5 minutes). It adds the widgets at the top, prefilled with this workspace's default catalog and a running SQL warehouse, checks everything, and installs. The app link is printed at the end.

That's it for most installs. The first three widgets are the ones that matter:

| Widget | What it is |
|---|---|
| **1. Catalog** | Where the toolkit creates its two schemas |
| **2. SQL warehouse** | What the app and jobs query through |
| **3. Schema for new model services** | Blank: `<catalog>.ug_migrated` is created for you. Or enter `catalog.schema` of a schema you already have, or want created |

To use another catalog or warehouse, change the widget and click **Run all** again. If the workspace has no default catalog you can use, the first run stops and asks you to pick one in **1. Catalog**.

Before anything changes, the notebook prints one checklist (shortened here):

```
Checklist:
  [OK  ] Databricks Apps: you can create apps
  [OK  ] Catalog: main (the results schema goes here)
  [OK  ] SQL warehouse: Serverless Starter Warehouse (0123456789abcdef) is running
  [FIX ] the SQL warehouse can't read system.serving.endpoint_usage (the snapshot and scans need SELECT on it). Ask an account admin to run: GRANT ...
  [OK  ] Schema for new model services: main.ug_migrated doesn't exist: it will be created
```

- **FIX** stops the install. Nothing is created or changed (a stopped SQL warehouse may have been started for the checks), and the cell ends with a red "Nothing was changed" error, which is expected. Fix each FIX item (the message has the exact `GRANT` or the widget to set), then Run all again.
- **NOTE** doesn't stop it. For example, if the schema for new model services can't be created, the install goes on, scans work, and Apply waits until the schema exists. The SQL to create it is printed.

When it finishes, open the app, wait a few minutes for the first snapshot, then go to **Scans** and click **Start scan**.

## Optional widgets

Widgets 4 to 17 are marked **(optional)**. Most installs leave them blank. Blank keeps the default, or what the install already in the workspace uses; `none` clears a setting.

| Widget | Use it for |
|---|---|
| 4. App name | A second install. An older install (`unity-gateway-migration` from 0.8, `ug-migration` from 0.7) is found without it when it's the only one |
| 5. Operators | Who can start jobs in the app. Default: you |
| 6. Run jobs as service principal | A shared install: the jobs run as this service principal. Its name or application ID. You need its **Service principal: User** role |
| 7. Create schema 3 if it's missing | `no` if you'll create it yourself (the SQL is printed) |
| 8, 9. Results schema name, install folder | Other locations |
| 10, 11. Allowed secret schemas, allow reading secret values | Secret mapping in Apply |
| 12. Legacy deadline | A date other than March 30, 2027 |
| 13, 14. Central mode | One install that also manages other workspaces. See [Central mode](#central-mode) |
| 15 to 17. Adopt an existing app, allow downgrade, allow a second install | Special cases. The checklist tells you when you need one |

A job that runs the installer passes the widget names as parameters (`01_catalog`, `06_run_as`, ...).

## Central mode

One install (the hub) can also scan and change other workspaces in the account. Most customers don't need it: installing the toolkit in each workspace is simpler. If you do want it:

1. **A service principal** that is a workspace admin in each workspace to manage. Enter its name or application ID in **6. Run jobs as service principal**.
2. **A Databricks OAuth secret** for it: Settings > Identity and access > Service principals > the service principal > **Secrets** > Generate secret. This is a Databricks secret, not an Entra ID (Azure) client secret.
3. **Store it in a Databricks secret scope** the service principal can read:
   ```
   databricks secrets create-scope ugmig
   databricks secrets put-secret ugmig sp_secret
   databricks secrets put-acl ugmig <application ID> READ
   ```
   Enter `ugmig/sp_secret` in **14. Central mode: OAuth secret**.
4. **The workspace IDs** to manage in **13. Central mode: workspace IDs**.
5. **Network policies.** The toolkit's jobs run on serverless compute, and Databricks only lets serverless compute in one workspace call another when cross-workspace network policies allow it. An account admin enables the **Cross Workspace Network Policy** preview, then, in the account console (Security > Networking), adds the managed workspaces as allowed Databricks destinations in the hub's serverless egress policy, and allows the hub in each managed workspace's ingress policy. Without this, scans of the other workspaces fail with "Cert validation failed ... trusted workload checks did not pass". See [cross-workspace access](https://learn.microsoft.com/en-us/azure/databricks/security/network/front-end/cross-workspace-access) (Beta).

The checklist checks the secret scope, the key and the service principal's READ, and reminds you of the network policies.

## Update

Import the newer installer and click **Run all**. With an install already in the workspace, **1. Catalog** and **2. SQL warehouse** start at "keep the current one", and every setting is kept: catalog and schemas, warehouse, operators, the jobs' service principal, central mode and secret mapping. The run lists what it kept.

**Updating from 0.10 or earlier:** those installs didn't record their operators, and Databricks doesn't return them, so the first update asks for them once (a FIX). Enter them in **5. Operators** (your email alone is fine), then Run all again. Later updates keep them.

The [user guide](USER_GUIDE.md#installer-widgets) lists every widget, and [Troubleshooting](USER_GUIDE.md#9-troubleshooting) maps each installer message to its fix.

## Uninstall

Import `UNINSTALL_unity_gateway_migration_toolkit_0_11_0.py` from the same zip. Run all with **1. Action** = `preview` first: it lists what would be removed and kept, and changes nothing. Then set **1. Action** to `remove` and Run all again. Model services created by Apply stay unless you set **3. Roll back services** to `yes`. See [Uninstall and cleanup](USER_GUIDE.md#6-uninstall-and-cleanup).
