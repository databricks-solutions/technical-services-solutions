# DW Migration

Solutions and accelerators for migrating data warehouses onto the Databricks Lakehouse. This track covers schema conversion, data movement, and query migration from legacy warehouse platforms.

## Projects

| Project | Description |
|---|---|
| [source-extracts](source-extracts) | Offline extractors that write local `.sql` files for Lakebridge Analyzer. Snowflake is first; add other engines as sibling folders. |
| [utilities/utf8-conversion](utilities/utf8-conversion) | Convert exported code (SQL, SSIS, other XML) from UTF-16 to UTF-8 before Lakebridge / Genie Migrate. Single-file commands, plus bulk scripts for macOS/Linux (bash) and Windows (PowerShell). |
