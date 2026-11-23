# UG Migration Toolkit installer review

**Review date:** 2026-11-13
**Scope:** installer and first-run experience on `main`, at commit `85f05bd` (v0.10.3). The toolkit files on `origin/main` are the same. This review uses the customer feedback and meeting notes supplied with the request.

The 0.11.0 changes in those notes are proposals from another branch, not behavior on `main`. In particular, `main` does not have a separate uninstall notebook or `INSTALL.md`, and it does not create `<catalog>.ug_migrated`.

This document proposes future behavior for discussion; it does not change the installer.

## Short recommendation

Keep the single-notebook installer, but replace the widget panel with one small Python call. Auto-detect safe defaults, show a complete installation plan on the first run, and require an explicit `preview=False` before any write. Use a separate uninstall notebook with preview as its default.

Make the two schemas distinct in names, documentation, and output:

| Purpose | Recommended default | Created by the installer? |
|---|---|---|
| App results: scans, applies, snapshots, operators | `<catalog>.ug_migration` | Yes |
| New model services created by Apply | `<catalog>.ug_migrated` | Yes, after confirmation; an existing schema is also allowed |

These are the single-workspace defaults. In central mode, use a separate target per managed workspace, such as `<catalog>.ug_migrated_<workspace_id>`, so workspaces sharing a metastore cannot collide. The central preview must include each remote schema and its grants, or list them explicitly as prerequisites.

Keep bundles for CI/CD and repeat deployments. Do not make a CLI, YAML, Marketplace, or a second advanced installer part of the first-time customer path.

## What `main` does today

- The notebook creates **19 widgets** in one panel, mixing install, advanced, central-mode, and uninstall choices ([installer lines 54-73](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/installer/install_template.py#L54-L73), [widget reference](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/USER_GUIDE.md#installer-widgets)).
- A fresh install requires a catalog choice. A warehouse is preselected only when the workspace has exactly one; otherwise the admin must choose ([installer lines 41-57](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/installer/install_template.py#L41-L57)).
- The installer's default target and target check are hard-coded to `ai_gateway.migrated`. It does not create that schema; the admin must create it or select another existing schema in Apply ([target check](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/installer/install_template.py#L1385-L1392), [first-run instructions](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/USER_GUIDE.md#2-first-run)).
- Preflight can start a warehouse and create the results schema. This matters when designing a read-only preview ([preflight](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/installer/install_template.py#L828-L831)).
- Installation starts the account-wide snapshot. The confirmation plan therefore needs to name its scope and the job identity, not only the objects created ([first snapshot](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/installer/install_template.py#L1374-L1384)).
- A bundle already exists for users who want source-controlled, repeatable deployment ([`databricks.yml`](https://github.com/databricks-solutions/technical-services-solutions/blob/85f05bd2ea7fa700ab8a14d8dcf381c82befc3b1/unified-governance/unity-gateway-migration-toolkit/databricks.yml)).

The main usability problem is not a lack of documentation. It is that the installer exposes every decision before the admin has enough context, while hiding the one target-schema decision that blocks Apply.

## Recommended customer flow

### 1. Import and preview

Import the notebook by URL and click **Run all**. The settings cell should need no edit:

```python
install(
    catalog=None,        # None = workspace default catalog
    warehouse=None,      # None = existing install, else an unambiguous running warehouse
    target_schema=None,  # None = <catalog>.ug_migrated
    preview=True,        # read-only plan; no resources are created or started
)
```

Defaults should be discovered, not guessed:

- Reject `hive_metastore` with an actionable message.
- Reuse the current install's catalog, warehouse, and settings on updates.
- Use a running warehouse when exactly one is available. If several are running, stop and list their names; do not pick one for the customer.
- If a warehouse must be started, show that in the plan and start it only after confirmation.
- For a single workspace, create both default schemas only after confirmation. Validate and show grants for both the installing admin and the job identity.
- For central mode, include every managed workspace's distinct target schema and effective grants in the plan.

### 2. Review a short, explicit plan

Example output for a single workspace:

```text
OK    Workspace admin and required system tables
OK    Results location: main.ug_migration
NOTE  Results schema does not exist: it will be created
NOTE  Model-service target main.ug_migrated does not exist: it will be created
NOTE  Job identity: you (the installing admin)
NOTE  Create one app and three jobs; preserve all existing objects
NOTE  Start the first account-wide snapshot after installation
FIX   No running warehouse: choose one of Shared (id 123), Migration (id 456)

No changes were made. To install, set preview=False and Run all.
```

Use `OK` for checks that pass, `FIX` only when a person must act, and `NOTE` for defaults and actions the installer will take. Print the exact GRANT for every `FIX`. Do not hide important actions below long logs.

### 3. Confirm and install

The admin changes only `preview=False` and clicks **Run all** again. The same settings are reused, so there is nothing new to learn or fill in.

A second run is justified here: the installer creates an app, three jobs, two schemas, and starts an account-wide read. The first run should never create a schema or start a warehouse just to produce its preview.

### 4. Open the app

The final output should contain only:

- the app link;
- the results and model-service schemas;
- the job identity and snapshot status;
- the next action: **Scans > Start scan**;
- one link for viewer grants and one for troubleshooting.

## Answers to the three questions

### 1. Which installation pattern should we use?

Use a **small Python function call in the existing notebook**, following the pattern made familiar by dbdemos. This avoids the fresh-notebook widget lifecycle problem and keeps installation in the workspace with no CLI.

| Option | Recommendation | Why |
|---|---|---|
| Python notebook call | **Default** | No widget state, easy URL import, named optional arguments, and `help(install)` documents advanced settings without showing them all. |
| Always-visible widgets | **Remove** | They expose advanced and destructive decisions to every first-time admin and depend on cells running to appear or update. |
| Dynamic quick/custom toggle | **Do not retry** | It depends on notebook cell execution state, which the customer cannot be expected to understand. |
| Interactive `databricks labs install` | **Optional later** | UCX proves that guided prompts work well for CLI users, but requiring a CLI conflicts with this tool's simple workspace-install goal. |
| Bundle | **Keep for CI/CD** | The existing bundle is the right path for source-controlled, repeatable deployments, not the easiest first install for a workspace admin. |
| Separate simple and advanced installers | **Avoid duplication** | Keep one installer engine and one install notebook. Put central mode in a guided section with its three related settings, not in a second implementation. |
| Settings in the app | **Runtime settings only** | Operators fit in app Settings. Job identity, central allowlist/secret, app resources, and job-level secret policy must be settled before deployment and cannot move there. |
| Marketplace-style distribution | **Not now** | It adds packaging and publishing work without fixing catalog, schema, identity, or permission choices. Revisit only if adoption justifies another distribution channel. |

Advanced options should remain keyword arguments documented by `help(install)` and an advanced-install guide. Do not replace the widget wall with a mandatory YAML file or an optional-settings form on the basic path.

Use a **separate uninstall notebook** with `uninstall(preview=True)` as the default. This removes destructive choices from installation and prevents an accidental Action change from becoming a deletion request.

### 2. Should the first run install immediately?

**Auto-detect defaults, but do not auto-execute on the first run.** The first run should always show what will change and stop without writes. Set `preview=True` for install and uninstall alike.

This does not mean repeating the rejected “optional settings, then preview” design. The admin should not have to provide anything before the preview unless the installer cannot safely choose. The only required confirmation is one visible `preview=False` change after reading the result.

Updates should use the same rule: reuse every stored setting, show a concise diff, and apply only after confirmation. Start the first snapshot only after the confirmed install.

### 3. Which existing patterns are worth copying?

- **[dbdemos](https://github.com/databricks-demos/dbdemos):** copy the small `dbdemos.install(...)` calling convention, not its dependency or packaging. A named Python call is easier to understand than a panel of widgets.
- **[UCX installation](https://databrickslabs.github.io/ucx/docs/installation/index.html):** `databricks labs install ucx` uses guided prompts for an inventory database, warehouse, and other configuration, then saves a confirmed configuration. Its uninstall also defaults destructive artifact and database removal to **no**. Copy that guided, safe-default behavior if a CLI installer is added later.
- **[Declarative Automation Bundles](https://docs.databricks.com/en/dev-tools/bundles/index.html):** keep the existing bundle as the infrastructure-as-code path for teams, review, and CI/CD. Do not force that workflow onto a one-time workspace admin.

## Prioritized simplification backlog

| Priority | Change | Acceptance check |
|---|---|---|
| P0 | Replace the 19-widget panel with the small Python call and advanced keyword arguments. | A fresh import needs no widget cell and no widget cleanup. `help(install)` exposes every advanced option without showing it on the basic path. |
| P0 | Make preview genuinely read-only. | A FakeWS snapshot before and after preview is identical: no schema, warehouse start, files, jobs, app, grants, or snapshot run. |
| P0 | Document and create the two schemas with distinct defaults. | On a workspace with no `ai_gateway` catalog, a confirmed install creates both schemas and makes `<catalog>.ug_migrated` the scan and Apply default. An Apply dry run for an eligible endpoint then succeeds without manual SQL, and the effective job-identity grants are verified. |
| P0 | Make ambiguous defaults fail with a specific choice. | Multiple running warehouses produce a short named choice, not an arbitrary warehouse or a panel of unrelated settings. |
| P1 | Move uninstall to its own notebook, preview first. | The install notebook cannot uninstall. Uninstall makes no changes until `preview=False`; destructive options remain off by default. |
| P1 | Add one-page `INSTALL.md`. | It covers prerequisites, the two-schema table, preview/confirm, update, central-mode link, and uninstall link in under five minutes. Move reference detail to `USER_GUIDE.md`. |
| P1 | Make central mode a guided optional path. | Single-workspace users never see central settings. Central setup asks for run-as identity, workspace allowlist, and secret reference together. A two-workspaces-on-one-metastore test verifies separate `<catalog>.ug_migrated_<workspace_id>` targets and their effective grants in each workspace. |
| P1 | Keep status and errors accessible. | `OK`, `FIX`, and `NOTE` are text, not color alone; plans read top-to-bottom at 200% zoom, links have descriptive names, and every error names the next action. No custom JavaScript is needed. |
| P2 | Show a concise update diff. | An update needs no input, reuses stored settings, and lists only changed resources and permissions before confirmation. |
| P2 | Offer CLI only if customers ask for it. | The notebook remains fully supported; any `databricks labs install` path reuses the same planner and safety checks rather than duplicating installation logic. |

## Suggested delivery slices

1. **Terminology and schema fix:** add the two-schema table, default the single-workspace model-service target to `<catalog>.ug_migrated`, create it after confirmation, and prove it with an Apply dry run. Cover per-workspace targets in the central-mode flow.
2. **Safe installer flow:** replace widgets with the Python call, split read-only planning from execution, and add preview and update tests.
3. **Lifecycle cleanup:** separate uninstall, add `INSTALL.md`, and move central-mode and other advanced detail out of the basic path.
4. **Optional distribution later:** add guided CLI installation only when there is demonstrated demand; keep the bundle for CI/CD.

## Verification notes

This was a code and documentation review, not a fresh-workspace installation test. The full `main` test suite was run after this documentation-only change: **655 Python tests passed**. No live workspace, Marketplace, or CLI installation was exercised.
