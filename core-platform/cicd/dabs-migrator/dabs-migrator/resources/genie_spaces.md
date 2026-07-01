# Resource: `genie_spaces`

AI/BI Genie spaces — natural-language data rooms backed by a SQL warehouse. One YAML per space under `resources/genie_spaces/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#genie_space

## Source

**If migrating an existing Genie space:** export the original space definition and place it verbatim. Run `databricks bundle generate genie-space` to round-trip an existing space into the bundle — this writes the serialized body to a `.geniespace.json` file. Reference it via `file_path: ../../src/{{ genie_space_name }}/space.geniespace.json` rather than inlining `serialized_space`. Do not edit, prettify, or simplify the exported JSON.

**Stub (only when starting from scratch):** set `title`, `warehouse_id`, and a short `description`, then author the space in the UI and export it back into the file.

## Complete schema reference

```yaml
resources:
  genie_spaces:
    <genie_space_name>:
      description: <string>  # string | Description of the Genie space shown alongside the title in the Databricks UI.
      etag: <string>  # string
      file_path: <string>  # string | Local path to a `.geniespace.json` file holding the serialized Genie space defin
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      parent_path: <string>  # string | Workspace folder under which to create the Genie space. Immutable: changing this
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      serialized_space: <any>  # any | Serialized Genie space body. May be provided inline as a JSON string (or YAML th
      title: <string>  # string | Title of the Genie space shown in the Databricks UI.
      warehouse_id: <string>  # string | ID of the SQL warehouse used to run queries for this Genie space.
```

## What to ask the user

- Existing Genie space to export, or build new?
- Which SQL warehouse runs the queries?
- Inline `serialized_space` or reference an exported `file_path`?
