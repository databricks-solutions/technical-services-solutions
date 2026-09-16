# Lakeflow Connect

Examples and tools for [Lakeflow Connect](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect) ingestion patterns.

## Projects

### [SQL Server CDC](./sql-server-cdc/)

DABs bundle that deploys an ingestion gateway and CDC ingestion pipeline for SQL Server via a Unity Catalog federated connection, with optional scheduled refresh. Includes an [agent runbook](./sql-server-cdc/RUNBOOK.md) for guided setup.

### [Lakeflow CDC Source Validator](./lakeflow-connectivity-validator/)

Pre-flight connectivity validator notebook that verifies DNS, TCP, TLS, and optional application-level database access from Databricks compute before deploying a Lakeflow CDC connector. Supports SQL Server, PostgreSQL, and MySQL, and reports egress IP, region match, and network path.
