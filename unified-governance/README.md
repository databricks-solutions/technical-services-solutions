# Unified Governance

Solutions and accelerators for unified governance with Databricks Unity Catalog. This track covers data and AI asset governance, access control, lineage, and compliance patterns.

## Projects

| Project | Description |
|---|---|
| [unity-gateway-migration-toolkit](unity-gateway-migration-toolkit/) | Databricks App and toolkit to move legacy model serving endpoints (AI Gateway v1 and v2) to Unity Gateway, governed by Unity Catalog: account snapshot, per-workspace readiness for Enforce Unity Gateway, code fixes for callers, apply/rollback of model services and grants, and verify and cut-over steps (traffic check, usage tracking, pausing legacy endpoints, test calls, Unity Gateway usage). Replaces the official migration runbook notebook. Installs from a single notebook. |
| [unity-gateway-readiness](unity-gateway-readiness/) | Databricks notebook that checks end to end whether a workspace is ready for production Unity Gateway traffic: metastore, region, and admin roles, target model and MCP services, grants, live calls on every supported API, Azure ADI Services, custom service creation, usage and billing tables, and cost controls. Ends with a verdict dashboard, a model-by-check matrix, and a fix for every failure. |
