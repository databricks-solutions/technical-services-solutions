# Production Readiness

Solutions and accelerators for taking Databricks workloads to production: CI/CD with Declarative Automation Bundles (DABs) and MLOps.

## CI/CD

| Project | Description |
|---|---|
| [dabs-migrator](../core-platform/cicd/dabs-migrator) | Genie Code skill that converts existing workspace assets (jobs, pipelines, dashboards, apps) into a DABs project, with per-resource YAML, tests, and a CI/CD pipeline |
| [customer-360-lakehouse-genie](../core-platform/cicd/customer-360-lakehouse-genie) | End-to-end example: a Customer 360 lakehouse with Genie Agents, deployed with DABs |
| [orderflow-app-lakebase](../core-platform/cicd/orderflow-app-lakebase) | End-to-end template: an order and inventory Databricks App on Lakebase (Postgres) |

CI/CD projects currently live under `core-platform/cicd/` and will move into this folder.

## MLOps

| Project | Description |
|---|---|
| [mlops-quickstart](https://github.com/databricks-solutions/mlops-quickstart) | End-to-end MLOps example: feature table, model training in Unity Catalog, an MLflow 3 deployment job, batch and real-time inference, and DABs with GitHub Actions or Azure DevOps |
