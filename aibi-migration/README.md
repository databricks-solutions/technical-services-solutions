# AIBI Migration

Solutions and accelerators for migrating business intelligence and analytics workloads onto Databricks AI/BI. This track covers moving dashboards, reports, and semantic models from legacy BI platforms.

## Projects

- **[aibi-migration-map](./aibi-migration-map/)** — Turn a raw Tableau or Power BI estate into a
  single self-contained HTML migration map: every workbook routed to the Databricks AI/BI asset that
  replaces it (Lakeview dashboard / Genie space / App / SQL Alert), the mirror view, and a Metric
  View blueprint for the shared semantic layer.
- **[uc-semantics-migration-map](./uc-semantics-migration-map/)** — Consolidate the concepts a BI
  estate defines many ways (Net Revenue, Active Customers…) into governed Unity Catalog Domains,
  Metric Views, Pages and Wikis. Read-only assessment first, human approval, then idempotent
  implementation.
