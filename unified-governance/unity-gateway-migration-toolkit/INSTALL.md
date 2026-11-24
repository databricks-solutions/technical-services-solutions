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
| Schema for new model services | `<catalog>.ug_migrated` | Empty until you run Apply. The service names end up in your callers' code (`<catalog>.ug_migrated.<service>`), so pick the schema you want to keep. Already have one? Set `target_schema` to it |
| Toolkit files | `/Workspace/Users/<you>/ug-migration-toolkit` | Replaced on every update |
| Three jobs | `[ug-migration-toolkit] Unity Gateway migration snapshot`, `workspace scan`, `apply` | Started from the app. Tagged `Project = unity-gateway-migration-toolkit`. The weekly snapshot is paused |
| The app | `ug-migration-toolkit` (Compute > Apps) | Where you work: Overview, Scans, Apply, Verify & cut over. Only operators (default: you) can start jobs in it; others can view |

The install never changes your endpoints or code. Changes happen later, only when you start them in the app.

## Install

1. Download `unity-gateway-migration-toolkit.zip` from the [release page](https://github.com/databricks-solutions/technical-services-solutions/releases/tag/unity-gateway-migration-toolkit-latest) and unzip it. In the workspace, open your home folder, choose **Import**, and import `INSTALL_unity_gateway_migration_toolkit_0_11_0.py` from the zip's top folder.
2. Open the notebook and click **Run all**. The first run checks the workspace and shows the checklist and plan under **Checklist and plan**, further down the notebook, but changes nothing (the small cell after it says `Notebook exited`).
3. Review the checklist, then set `preview=False` in `install(...)` and click **Run all** again to install. The app link is printed at the end.

The usual settings need no edit:

| `install(...)` argument | Default |
|---|---|
| `catalog` | `None`: the workspace's default catalog, or the current install's catalog. The toolkit creates its two schemas there |
| `warehouse` | `None`: the current install's warehouse, else an unambiguous running warehouse by name or ID |
| `target_schema` | `None`: `<catalog>.ug_migrated`, created after confirmation. Or use `catalog.schema` of an existing schema |
| `preview` | `True` interactively: show checks and the plan without writes. Set `False` to install |

If the default catalog isn't usable or several running warehouses are available, the checklist asks for one explicit choice instead of guessing.

Example checklist:

```
Checklist:
  [OK  ] Databricks Apps: you can create apps
  [OK  ] Catalog: main (the results schema goes here)
  [OK  ] SQL warehouse: Serverless Starter Warehouse (0123456789abcdef) is running
  [NOTE] Results schema: main.ug_migration will be created after you set preview=False
  [FIX ] the SQL warehouse can't read system.serving.endpoint_usage (the snapshot and scans need SELECT on it). Ask an account admin to run: GRANT ...
  [OK  ] Schema for new model services: main.ug_migrated doesn't exist: it will be created
```

- **Preview makes no writes.** A FIX stops there, or stops the confirmed install before any remaining resources change. After confirmation, a warehouse may already have started when a later system-table FIX appears.
- **NOTE** doesn't stop it. Preview never starts a warehouse or creates a schema. If the schema for new model services can't be created after confirmation, the install still finishes: scans work, and Apply waits with the SQL.

When installation finishes, open the app, wait a few minutes for the first snapshot, then go to **Scans** and click **Start scan**.

## Optional settings

`help(install)` lists every advanced keyword argument. `None` keeps the current install's setting or the documented default. To clear a setting the install already has (back to its default), pass `"none"` (or `"off"`); an empty list or string keeps it, like `None`. The yes/no settings (`create_target`, `allow_secret_read`, `adopt_app`, `allow_downgrade`, `second_install`) take `True` or `False` (`"yes"`/`"no"`, `"true"`/`"false"` and `1`/`0` work too, in any case, and `"y"`/`"n"` too); any other value stops the run before anything changes, with a message that names the setting. For the name settings (`app_name`, `catalog`, `results_schema`, `install_folder`, `warehouse`), `"none"` and `"off"` mean the same as `None`.

| Argument | Use it for |
|---|---|
| `app_name` | A second install. An older install (`unity-gateway-migration` from 0.8, `ug-migration` from 0.7) is found without it when it's the only one |
| `operators` | Who can start jobs in the app. Default: you. A list or comma-separated string works |
| `run_as` | A shared install: the jobs run as this service principal's name or application ID. You need its **Service principal: User** role |
| `create_target` | `False` if you'll create the model-service schema yourself (the SQL is printed) |
| `results_schema`, `install_folder` | Other locations |
| `secret_schemas`, `allow_secret_read` | Secret mapping in Apply. Lists or comma-separated schemas work |
| `deadline` | A date other than March 30, 2027 |
| `central_workspaces`, `central_secret` | One install that also manages other workspaces. See [Central mode](#central-mode) |
| `adopt_app`, `allow_downgrade`, `second_install` | Special cases. The checklist tells you when you need one |

Notebook jobs execute with `preview=False` and keep the old parameter names (`01_catalog`, `06_run_as`, ...), so existing automation doesn't stop at preview. New job parameters are used only when the corresponding `install(...)` argument is `None`.

## Central mode

One install (the hub) can also scan and change other workspaces in the account. Most customers don't need it: installing the toolkit in each workspace is simpler. If you do want it:

1. **A service principal** that is a workspace admin in each workspace to manage. Set `run_as` to its name or application ID.
2. **A Databricks OAuth secret** for it: Settings > Identity and access > Service principals > the service principal > **Secrets** > Generate secret. This is a Databricks secret, not an Entra ID (Azure) client secret.
3. **Store it in a Databricks secret scope** the service principal can read:
   ```
   databricks secrets create-scope ugmig
   databricks secrets put-secret ugmig sp_secret
   databricks secrets put-acl ugmig <application ID> READ
   ```
   Set `central_secret="ugmig/sp_secret"`.
4. Set `central_workspaces` to the workspace IDs to manage, as a list or comma-separated string. A workspace created in the last few hours may not be listed in `system.access.workspaces_latest` yet; scans of it fail until it is.
5. **Network policies.** The toolkit's jobs run on serverless compute, and Databricks only lets serverless compute in one workspace call another when cross-workspace network policies allow it. Without this, scans of the other workspaces fail with "Cert validation failed ... trusted workload checks did not pass". It isn't a credentials problem. An account admin, in the account console:
   - **Ingress (each managed workspace):** enables the **Cross Workspace Network Policy** preview (**Previews**), then in Security > Networking > Context-based ingress & egress, on the policy attached to that workspace, clears **Compatibility mode** on the **Ingress** tab and allows the hub's workspace ID under **Restrict access to specific source workspaces**. "Allow access from all public IPs" doesn't cover this. A policy named default-policy applies to every workspace without its own policy, so a dedicated policy for the managed workspace is safer.
   - **Egress (the hub):** nothing to do if its policy allows access to all destinations. If egress is restricted, add the managed workspaces under **Allowed Databricks workspace destinations**.

   See [cross-workspace access](https://learn.microsoft.com/en-us/azure/databricks/security/network/front-end/cross-workspace-access) (Beta). **Alternatives:** install the toolkit in each workspace instead, or run the scan and apply jobs on classic compute, which these policies don't govern (in Jobs, change each job's task compute from serverless to a job cluster, Standard access mode, Databricks Runtime 15.4 LTS or later; running the installer again puts them back on serverless).

The checklist checks the secret scope, the key and the service principal's READ, and reminds you of the network policies.

## Update

Import the newer installer and use the same `install(...)` call. `None` reuses every current setting: catalog and schemas, warehouse, operators, the jobs' service principal, central mode and secret mapping. The run lists what it kept.

**Updating from 0.10 or earlier:** those installs didn't record their operators, and Databricks doesn't return them, so the first update asks for them once (a FIX). Set `operators` (your email alone is fine), then Run all again. Later updates keep them.

The [user guide](USER_GUIDE.md#installer-settings) lists every setting, and [Troubleshooting](USER_GUIDE.md#9-troubleshooting) maps each installer message to its fix.

## Uninstall

Import `UNINSTALL_unity_gateway_migration_toolkit_0_11_0.py` from the same zip. Run all with **1. Action** = `preview` first: it lists what would be removed and kept, and changes nothing. Then set **1. Action** to `remove` and Run all again. Model services created by Apply stay unless you set **3. Roll back services** to `yes`. See [Uninstall and cleanup](USER_GUIDE.md#6-uninstall-and-cleanup).
