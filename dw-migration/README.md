# DW Migration

Solutions and accelerators for migrating data warehouses onto the Databricks Lakehouse. This track covers schema conversion, data movement, and query migration from legacy warehouse platforms.

## Projects

| Project | Description |
|---|---|
| [source-extracts](source-extracts) | Offline extractors that write local `.sql` files for Lakebridge Analyzer. Snowflake is first; add other engines as sibling folders. |
| [semantics-builder](semantics-builder) | STS Semantics Builder: a Databricks App that turns migrated tables into governed Unity Catalog metric views, from sources and intent to a validated, stress-tested and optimized design. |
