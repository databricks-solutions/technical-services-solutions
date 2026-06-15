# Resource: `dashboards`

AI/BI Dashboards (Lakeview).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#dashboard

## Source

**If migrating an existing dashboard:** export the original Lakeview dashboard JSON from the workspace and place it verbatim at `src/{{ dashboard_name }}/dashboard.lvdash.json`. Do not edit, prettify, or simplify the exported JSON — bundle deploy round-trips it as-is.

**Stub (only when starting from scratch):** create an empty `src/{{ dashboard_name }}/dashboard.lvdash.json`, then author in the UI and export back into the file.

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
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      lifecycle_state: ACTIVE  # enum: ACTIVE, TRASHED | The state of the dashboard resource. Used for tracking trashed status.
      parent_path: <string>  # string | The workspace path of the folder containing the dashboard. Includes leading slas
      path: <string>  # string | The workspace path of the dashboard asset, including the file name.
      permissions:  # array[object]
        -
          group_name: <string>  # string | The name of the group that has the permission set in level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The allowed permission for user, group, service principal defined for this permi
          service_principal_name: <string>  # string | The name of the service principal that has the permission set in level.
          user_name: <string>  # string | The name of the user that has the permission set in level.
      serialized_dashboard: <any>  # any | The contents of the dashboard in serialized string form.
      update_time: <string>  # string | The timestamp of when the dashboard was last updated by the user.
      warehouse_id: <string>  # string | The warehouse ID used to run the dashboard.
```

## What to ask the user

- Existing dashboard to export, or build new?
- Which warehouse runs the queries?
