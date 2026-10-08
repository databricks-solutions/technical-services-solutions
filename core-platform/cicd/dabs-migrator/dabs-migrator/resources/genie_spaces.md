# Resource: `genie_spaces`

AI/BI Genie spaces — natural-language data rooms backed by a SQL warehouse. One YAML per space under `resources/genie_spaces/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#genie_space

## Source

**If migrating an existing Genie space:** export the original space definition and place it verbatim. Run `databricks bundle generate genie-space` to round-trip an existing space into the bundle — this writes the serialized body to a `.geniespace.json` file. Reference it via `file_path: ../../src/{{ genie_space_name }}/space.geniespace.json` rather than inlining `serialized_space`. Do not edit, prettify, or simplify the exported JSON.

### Retrieving the serialized body (avoids the empty-space retry)

`databricks genie get-space <space_id>` returns only `title`/`description`/`warehouse_id`/`parent_path` — it does **not** include `serialized_space`. Copying from it deploys an empty space. Use one of:

```bash
# Resolve the id first (match on .title):
databricks genie list-spaces -p <profile> -o json 2>/dev/null | jq -r '.spaces[] | select(.title=="<name>") | .space_id'

# Then export the body — either round-trip into the bundle:
databricks bundle generate genie-space --existing-id <space_id> --key <name>
# ...or fetch the raw serialized_space via the API include flag:
databricks api get "/api/2.0/genie/spaces/<space_id>?include_serialized_space=true" -p <profile> 2>/dev/null
```

Redirect stderr with `2>/dev/null` before any `jq` — a proxied CLI banner on stderr corrupts piped JSON otherwise.

**Stub (only when starting from scratch):** set `title`, `warehouse_id`, and a short `description`, then author the space in the UI and export it back into the file.

## Migration must preserve the serialized space

When migrating an existing space, the generated resource **must** include `serialized_space` (inline JSON string) or `file_path` (to the exported `.geniespace.json`). Do not emit only `title`/`description`/`warehouse_id` — that deploys an **empty** space that passes `bundle validate` but has no tables, instructions, or sample questions. `serialized_space` is a JSON **string** (not a YAML object); its shape is:

```json
{"version":2,"data_sources":{"tables":[{"identifier":"<catalog>.<schema>.<table>"}]},"config":{"sample_questions":[{"id":"<hex32>","question":["…"]}]},"instructions":{"text_instructions":[{"id":"<hex32>","content":["…"]}]}}
```

`warehouse_id` and any table identifiers inside `serialized_space` must use bundle variables (`${var.warehouse_id}`, `${var.catalog}.${var.schema}.<table>`), not the concrete values the live read returns.

**Every `id` inside `serialized_space` must be a lowercase 32-character hex UUID with no hyphens** (e.g. `a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6`). This applies to `sample_questions[].id`, `instructions.text_instructions[].id`, and any other `id` field in the body. Placeholder or friendly ids like `q1` pass `bundle validate` but the create API rejects them: `Failed to parse export proto: Invalid id for sample_question.id: 'q1'. Expected lowercase 32-hex UUID without hyphens (400 INVALID_PARAMETER_VALUE)`. When migrating, keep the exported ids verbatim (they are already valid); when authoring from scratch, generate 32-hex ids (e.g. `python -c "import uuid;print(uuid.uuid4().hex)"`).

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
