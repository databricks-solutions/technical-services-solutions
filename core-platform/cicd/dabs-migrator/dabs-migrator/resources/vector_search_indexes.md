# Resource: `vector_search_indexes`

Vector Search index — a Delta Sync or Direct Access index served by a vector search endpoint. One YAML per index under `resources/vector_search_indexes/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#vector_search_index

## Common variations

- **Delta Sync index** — set `index_type: DELTA_SYNC` and populate `delta_sync_index_spec` (source table + embedding source/vector columns). The index stays in sync with the source Delta table.
- **Direct Access index** — set `index_type: DIRECT_ACCESS` and populate `direct_access_index_spec` (including `schema_json`). You write vectors directly via the API; there is no source table.
- Provide exactly one of `delta_sync_index_spec` / `direct_access_index_spec`, matching `index_type`.

## Complete schema reference

Required fields: `endpoint_name`, `index_type`, `name`, `primary_key`

```yaml
resources:
  vector_search_indexes:
    <vector_search_index_name>:
      delta_sync_index_spec:  # object | Specification for Delta Sync Index. Required if `index_type` is `DELTA_SYNC`.
        columns_to_index:  # array[string] | [Optional] Alias for columns_to_sync. Select the columns to include in the vecto
          - <value>
        columns_to_sync:  # array[string] | [Optional] Select the columns to sync with the vector index. If you leave this f
          - <value>
        embedding_source_columns:  # array[object] | The columns that contain the embedding source.
          -
            embedding_model_endpoint_name: <string>  # string | Name of the embedding model endpoint, used by default for both ingestion and que
            model_endpoint_name_for_query: <string>  # string | Name of the embedding model endpoint which, if specified, is used for querying (
            name: <string>  # string | Name of the column
        embedding_vector_columns:  # array[object] | The columns that contain the embedding vectors.
          -
            embedding_dimension: <int>  # int | Dimension of the embedding vector
            name: <string>  # string | Name of the column
        embedding_writeback_table: <string>  # string | [Optional] Name of the Delta table to sync the vector index contents and compute
        pipeline_type: TRIGGERED  # enum: TRIGGERED, CONTINUOUS | Pipeline execution mode.
        source_table: <string>  # string | The name of the source table.
      direct_access_index_spec:  # object | Specification for Direct Vector Access Index. Required if `index_type` is `DIREC
        embedding_source_columns:  # array[object] | The columns that contain the embedding source. The format should be array[double
          -
            embedding_model_endpoint_name: <string>  # string | Name of the embedding model endpoint, used by default for both ingestion and que
            model_endpoint_name_for_query: <string>  # string | Name of the embedding model endpoint which, if specified, is used for querying (
            name: <string>  # string | Name of the column
        embedding_vector_columns:  # array[object] | The columns that contain the embedding vectors. The format should be array[doubl
          -
            embedding_dimension: <int>  # int | Dimension of the embedding vector
            name: <string>  # string | Name of the column
        schema_json: <string>  # string | The schema of the index in JSON format.
      endpoint_name: <string>  # REQUIRED | string | Name of the endpoint to be used for serving the index
      grants:  # array[object] | The Unity Catalog privileges to grant to principals on this securable.
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[string] | The privileges assigned to the principal.
            - <value>
      index_subtype: VECTOR  # enum: VECTOR, FULL_TEXT, HYBRID | [Beta] The subtype of the index. Use `HYBRID` or `FULL_TEXT`. `VECTOR` is not su
      index_type: DELTA_SYNC  # REQUIRED | enum: DELTA_SYNC, DIRECT_ACCESS | There are 2 types of AI Search indexes:
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Name of the index
      primary_key: <string>  # REQUIRED | string | Primary key of the index
```

## What to ask the user

- Delta Sync (synced from a UC table) or Direct Access (write vectors via API)?
- Which serving endpoint (`endpoint_name`) and primary key column?
- Embedding source column + model endpoint, or precomputed embedding vector column?
