# DW Migration

Solutions and accelerators for migrating data warehouses onto the Databricks Lakehouse. This track covers schema conversion, data movement, and query migration from legacy warehouse platforms.

## Projects

| Project | Description |
|---|---|
| [source-extracts](source-extracts) | Offline extractors that write local `.sql` files for Lakebridge Analyzer. Snowflake is first; add other engines as sibling folders. |
| [utilities](utilities) | Tools on top of Lakebridge outputs. [sts-lb-lineage](utilities/sts-lb-lineage): lineage, process map, statistics, and impact analysis from Analyzer JSON. |
