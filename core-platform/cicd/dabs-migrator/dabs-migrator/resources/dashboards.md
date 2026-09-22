# Resource: `dashboards`

AI/BI Dashboards (Lakeview).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#dashboard

## Source

**If migrating an existing dashboard:** export the original Lakeview dashboard JSON from the workspace and place it verbatim at `src/{{ dashboard_name }}/dashboard.lvdash.json`. Do not edit, prettify, or simplify the exported JSON — bundle deploy round-trips it as-is.

**Stub (only when starting from scratch):** create an empty `src/{{ dashboard_name }}/dashboard.lvdash.json`, then author in the UI and export back into the file.

### Export the *serialized dashboard*, not the raw API resource tree

There are two very different JSON shapes and only one deploys. The correct source is the dashboard's **`serialized_dashboard`** payload (what `databricks bundle generate dashboard --existing-path <path>` writes, or the `serialized_dashboard` field from `GET /api/2.0/lakeview/dashboards/{id}`). It uses **short local slug `name`s** for `datasets`, `pages`, and `widgets`.

Do **not** reconstruct the `.lvdash.json` from the API's fully-qualified resource tree. That path (e.g. `GET .../dashboards/{id}/datasets`) returns objects whose identifiers are full resource paths like `dashboards/01f19.../datasets/01f19...`. If those land in the lvdash `name` fields, deploy fails validation (validate still passes):

```
resource names should only contain alphanumeric characters (a-z, A-Z, 0-9), hyphens (-), or underscores (_)
[dashboard.datasets[...].name] exceeds length limit of 63
[dashboard.pages[...].layout[0].position] should not be empty
```

Requirements for a deployable `.lvdash.json`:
- Every `datasets[].name`, `pages[].name`, and each `layout[].widget.name` must be a slug: only `a-z A-Z 0-9 - _`, **no slashes**, **≤ 63 chars**. Never use the API resource path as a `name`.
- Every `pages[].layout[]` entry must carry a non-empty `position` object (`{x, y, width, height}`). Don't drop it.

The safe rule: take `serialized_dashboard` verbatim — it already satisfies all of the above — rather than assembling the JSON yourself from per-collection API reads.

### Retrieving it (one read, no per-collection assembly)

Unlike Genie, the dashboard GET returns the serialized body inline — resolve the id, then read it in one call:

```bash
# Resolve the id (match on .display_name):
databricks lakeview list -p <profile> -o json 2>/dev/null | jq -r '.[] | select(.display_name=="<name>") | .dashboard_id'
# Read the dashboard; serialized_dashboard is a field on the response:
databricks lakeview get <dashboard_id> -p <profile> -o json 2>/dev/null | jq -r '.serialized_dashboard'
# (equivalently: databricks bundle generate dashboard --existing-path <path>)
```

Redirect stderr with `2>/dev/null` before `jq` — a proxied CLI banner on stderr otherwise corrupts the piped JSON (`jq: parse error: Invalid numeric literal`). Do **not** fall back to `GET .../dashboards/{id}/datasets` and friends; that is the per-collection tree that produces the invalid `name`s above.

## Complete schema reference

```yaml
resources:
  dashboards:
    <dashboard_name>:
      create_time: <string>  # string | The timestamp of when the dashboard was created.
      dashboard_id: <string>  # string | UUID identifying the dashboard.
      dataset_catalog: <string>  # string | Sets the default catalog for all datasets in this dashboard. When set, this over
      dataset_schema: <string>  # string | Sets the default schema for all datasets in this dashboard. When set, this overr
      display_name: <string>  # string | The display name of the dashboard.
      embed_credentials: <bool>  # bool
      etag: <string>  # string | The etag for the dashboard. Can be optionally provided on updates to ensure that
      file_path: <string>  # string
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      lifecycle_state: ACTIVE  # enum: ACTIVE, TRASHED | The state of the dashboard resource. Used for tracking trashed status.
      parent_path: <string>  # string | The workspace path of the folder containing the dashboard. Includes leading slas
      path: <string>  # string | The workspace path of the dashboard asset, including the file name.
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      serialized_dashboard: <any>  # any | The contents of the dashboard in serialized string form.
      update_time: <string>  # string | The timestamp of when the dashboard was last updated by the user.
      warehouse_id: <string>  # string | The warehouse ID used to run the dashboard.
```

## What to ask the user

- Existing dashboard to export, or build new?
- Which warehouse runs the queries?
