# Install the Unity Gateway Migration Toolkit

One notebook installs everything inside your workspace in about 5 minutes. No CLI, Git or local setup.

## What you need

| Need | Why | If it's missing |
|---|---|---|
| Workspace admin | The installer creates an app and three jobs | Ask a workspace admin to run the installer |
| A catalog where you have `USE CATALOG` and `CREATE SCHEMA` | The toolkit creates its two schemas there (below) | The checklist prints the `GRANT` to send the catalog owner |
| `CAN USE` on a SQL warehouse | The app and jobs query through it | Ask a workspace admin for one |
| `SELECT` on four system tables: `system.serving.endpoint_usage`, `system.serving.served_entities`, `system.ai_gateway.usage`, `system.access.workspaces_latest` | Legacy endpoints and their traffic come from them | The checklist prints the `GRANT` to send an account admin |

## What it creates

| What | Name (defaults) | Notes |
|---|---|---|
| Results schema | `<catalog>.ug_migration` | Scan results and history. Keep it to the migration team: scans store matched code lines |
| Schema for new model services | `<catalog>.ug_migrated` | Empty until you run Apply. The service names end up in your callers' code (`<catalog>.ug_migrated.<service>`), so pick the schema you want to keep. Already have one? Enter it in widget 3 |
| Toolkit files | `/Workspace/Users/<you>/ug-migration-toolkit` | Replaced on every update |
| Three jobs | `[ug-migration-toolkit] Unity Gateway migration snapshot`, `workspace scan`, `apply` | Started from the app. Tagged `Project = unity-gateway-migration-toolkit`. The weekly snapshot is paused |
| The app | `ug-migration-toolkit` (Compute > Apps) | Where you work, from Overview to Enforce |

The install never changes your endpoints or code. Changes happen later, only when you start them in the app.

## Install

1. Download `unity-gateway-migration-toolkit.zip` from the [release page](https://github.com/databricks-solutions/technical-services-solutions/releases/tag/unity-gateway-migration-toolkit-latest) and unzip it. In the workspace, open your home folder, choose **Import**, and import `INSTALL_unity_gateway_migration_toolkit_0_11_0.py` from the zip's top folder.
2. Open the notebook and set the widgets at the top:

   | Widget | What to set |
   |---|---|
   | **1. Catalog** | The catalog for the toolkit's two schemas |
   | **2. SQL warehouse** | Preselected when there's only one |
   | **3. Schema for new model services** | Leave blank to have `<catalog>.ug_migrated` created for you. Or enter `catalog.schema` of a schema you already have, or want created |
   | **4. Setup** | Leave at `quick` |

3. Click **Run all**.

Before anything changes, the notebook checks everything and prints one checklist:

```
Checklist:
  [OK  ] Databricks Apps: you can create apps
  [OK  ] Catalog: main (the results schema goes here)
  [OK  ] SQL warehouse: Serverless Starter Warehouse (0123456789abcdef) is running
  [FIX ] the SQL warehouse can't read system.serving.endpoint_usage (...): ask an account admin to run: GRANT ...
  [OK  ] Schema for new model services: main.ug_migrated doesn't exist: it will be created
```

- **FIX** stops the install, and nothing is changed. Fix each FIX item (the message has the exact `GRANT` or the screen to open), then Run all again.
- **NOTE** doesn't stop it. For example, if the schema for new model services can't be created, the install goes on, scans work, and Apply waits until the schema exists. The SQL to create it is printed.

When it finishes, it prints the app link. Open the app, wait a few minutes for the first snapshot, then go to **Scans** and click **Start scan**.

## Update

Import the newer installer and click **Run all**, with no widgets changed. It finds the install already in the workspace and keeps its settings: catalog and schemas, warehouse, operators, the jobs' service principal, central mode and secret mapping. The run lists what it kept.

## Custom setup

Set **4. Setup** to `custom` and click **Run all**. Widgets 5 to 18 appear, and the run stops so you can set them. Set what you need, then Run all again. Blank keeps the default, or what the install already uses. `none` clears a setting.

| Widget | Use it for |
|---|---|
| 5. App name | A second install, or an install from before 0.9 (`unity-gateway-migration`) |
| 6. Operators | Who can start jobs in the app. Default: you |
| 7. Run jobs as service principal | A shared install. You need the service principal's **Service principal: User** role |
| 8. Create the schema in 3 if it's missing | `no` if you'll create it yourself. The SQL is printed |
| 9, 10. Results schema name, install folder | Other locations |
| 11, 12. Allowed secret schemas, allow reading secret values | Secret mapping in Apply |
| 13. Legacy deadline | A date other than March 30, 2027 |
| 14, 15. Central mode | One install that also manages other workspaces |
| 16 to 18. Adopt an existing app, allow downgrade, allow a second install | Special cases. The checklist tells you when you need one |

The [user guide](USER_GUIDE.md#installer-widgets) has every widget, and [Troubleshooting](USER_GUIDE.md#9-troubleshooting) maps each installer message to its fix.

## Uninstall

Import `UNINSTALL_unity_gateway_migration_toolkit_0_11_0.py` from the same zip. Run all with **1. Action** = `preview` first: it lists what would be removed and kept, and changes nothing. Then set **1. Action** to `remove` and Run all again. Model services created by Apply stay unless you set **3. Roll back services** to `yes`. See [Uninstall and cleanup](USER_GUIDE.md#6-uninstall-and-cleanup).
