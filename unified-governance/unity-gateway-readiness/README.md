# Unity Gateway Readiness Check

A Databricks notebook that checks, end to end, whether a workspace is ready to run production traffic through Unity Gateway. It inventories the target model and MCP services, reads their grants and limits, makes small live calls on every supported API, checks usage, spend, and cost controls, and ends with a verdict dashboard.

Each check returns `PASS`, `FAIL`, `WARN`, `INFO`, `MANUAL`, or `SKIP`. Every `FAIL` and `WARN` comes with the fix.

## Requirements

**Role.** Run the notebook as a workspace admin who is also a metastore admin. Account admin adds the most coverage. The `system.ai_gateway` usage and spend tables are readable only by account and metastore admins by default, and reading another principal's grants needs `MANAGE` or ownership. Section 1 reports which roles the running identity holds.

Run it twice for a full picture:

1. As an admin, for the complete inventory, grants, usage, and cost data.
2. As the production identity, to prove that identity's real access. For a service principal, run a job with **Run as** set to that SP. Setting Run as needs the Service Principal User role on the SP.

Any `FAIL` blocks `READY`, and sections 7, 8, and 9 return `FAIL` when the identity cannot read the usage and billing tables. So the production-identity pass is `READY` only if that identity has `USE SCHEMA` and `SELECT` on `system.ai_gateway.usage`, `system.ai_gateway.external_model_spend`, `system.billing.usage`, and `system.billing.list_prices`. If you prefer not to grant those, expect `FAIL` on those reads in that pass and read the verdict from the other sections.

| Requirement | Needed for |
|---|---|
| Workspace admin | Reading other principals' access and workspace settings |
| Metastore admin, or `MANAGE` on `system.ai` | Effective grants on `system.ai` model and MCP services |
| Account admin, or `SELECT` on `system.ai_gateway` | `system.ai_gateway.usage` and `external_model_spend` |
| `SELECT` on `system.billing.usage` and `system.billing.list_prices` | Spend by model service |
| `EXECUTE` on each target model and MCP service | Live probes |
| `USE CATALOG`, `USE SCHEMA`, `CREATE SERVICE` on `test_schema` | Optional custom service round trip |
| `CREATE TABLE` on the target schema | Optional `results_table` write |

**Platform.** Unity Catalog enabled, a workspace in a Unity Gateway supported region (not AWS GovCloud), and compute that can reach the workspace host over HTTPS.

**Compute.** Serverless only, environment 6. The notebook pins environment 6 in its header, because the scorecard cell needs Python 3.12.

## How to run

1. Import `unity_gateway_readiness.py` into the workspace (Workspace > Import, or `databricks workspace import --format SOURCE --language PYTHON`).
2. Attach serverless compute and set the widgets. `target_models` and `target_mcp_services` take comma-separated names. A bare name such as `gpt-6-astra` is read as `system.ai.gpt-6-astra`. The default `target_models` are examples. Replace them with the models the customer will use, because a target that is not in `system.ai` for the workspace is a `FAIL`. `target_mcp_services` is blank by default. Not every workspace has every `system.ai` MCP service, for example `system.ai.web_search`.
3. Run all cells. Each section ends with a card of its checks. Section 10 shows the verdict, a model-by-check matrix, blockers with fixes, and the manual checklist.
4. Clear outputs before you share the notebook or its export. Outputs include grants, usage, and spend for the workspace.

To test a service principal, run the notebook as a job with **Run as** set to that principal and pass the widgets as job parameters. Anyone with `CAN MANAGE RUN` on the job can change the parameters, and the run uses the SP's privileges, so the notebook validates `results_table`, `test_schema`, and caps `burst_requests` at 20.

## Sections

| Section | What it verifies |
|---|---|
| 1. Platform | Metastore, cloud, region, GovCloud exclusion, caller identity and admin roles, gateway API reachability |
| 2. Model catalog | Each target model has a model service, live destinations, supported APIs, rate limits, inference table |
| 3. Access | `system` / `system.ai` / per-service grants for `account users` and an optional principal |
| 4. Invocation | Live call on every supported API, streaming, `ai_query`, optional parallel burst to surface 429s |
| 5. Azure ADI Services | On Azure Databricks, which targets are delivered through ADI, and live proof that ADI is enabled |
| 6. Custom services | `CREATE SERVICE` on a schema, optional create, query, delete round trip, provider and MCP inventory |
| 7. MCP services | Each target MCP service exists, tool selection, rate limits, grants, a live `tools/list` call, recent MCP traffic |
| 8. Observability | `system.ai_gateway.usage`, `external_model_spend`, `system.billing.usage`, probe rows landing in usage |
| 9. Cost controls | Rate limit coverage, service and request tags, spend by model service, prompt cache, reasoning and priority tier use, budgets |
| 10. Scorecard | Verdict, model-by-check matrix, blockers, manual checklist, optional Delta table write |

## Side effects

- Probes send a few prompts of about 20 tokens per model. The optional burst sends `burst_requests` more per model.
- MCP probes call `initialize` and `tools/list` only. They never call a tool.
- The only write is the opt-in temporary model service in section 6, which the notebook deletes in a `finally` block.
- Probe traffic carries the request tags `tool=ug_readiness` and a unique `readiness_run_id`, so it is easy to filter in usage tables.

## Limitations

- Budgets, cross-geography routing, the ADI Services toggle, and service policies have no workspace API. They are reported as `MANUAL` items.
- With `run_invocation_probes = no`, nothing proves access, so the verdict is `NOT VERIFIED` instead of `READY`.
- Usage, spend, and billing queries filter to the running workspace's `workspace_id`, so traffic from other workspaces in the account is not counted.
- Usage table ingestion can lag 20 minutes or more, so the probe-ingestion check returns `WARN` on timeout, not `FAIL`.
- Effective-permission reads do not always reflect grants inherited through nested group membership. The live probes are the authoritative access test for the running identity.
- The cache and reasoning thresholds in section 9 are heuristics for finding the largest cost levers, not limits.

## Disclaimer

This notebook is provided **as-is** for guidance and educational purposes. It is **not an official Databricks tool** or supported product.
