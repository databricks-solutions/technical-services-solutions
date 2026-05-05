# Data Warehousing

Below you will find Lakebridge-related samples and utilities you can adapt for migrations and validation on Databricks.

## Projects

### [Lakebridge Transpiler utilities](./lakebridge-transpiler-utilities/)

Samples and scripts to help you migrate legacy ETL to Databricks with [Lakebridge](https://databrickslabs.github.io/lakebridge). Start with the [transpiler overview](./lakebridge-transpiler-utilities/README.md), then open the folder for your source system for full instructions. If your environment blocks `.sh` downloads, those folders often include **`run.txt`** with the same script so you can copy or rename it after transfer.

### [Lakebridge Reconcile utilities](./lakebridge-reconcile-utilities/)

Notebooks and guides to reconcile Snowflake or SQL Server against Delta tables in Unity Catalog. Start with the [reconcile overview](./lakebridge-reconcile-utilities/README.md). Choose [Snowflake](./lakebridge-reconcile-utilities/snowflake_reconcile_automation/) or [SQL Server](./lakebridge-reconcile-utilities/sql_server_reconcile_automation/) for step-by-step setup.

### [Lakebridge Analyzer examples](./lakebridge-analyzer-examples/)

Sample Analyzer workbooks (Azure Synapse). See the [analyzer examples overview](./lakebridge-analyzer-examples/README.md).

### [Lakebridge Profiler examples](./lakebridge-profiler-examples/)

Sample Profiler extracts (Synapse-style). See the [profiler examples overview](./lakebridge-profiler-examples/README.md).
