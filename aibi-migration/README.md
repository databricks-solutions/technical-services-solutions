# AI/BI Migration

Resources and accelerators for migrating existing business intelligence workloads —
dashboards, reports, and semantic models from tools such as Tableau and Power BI —
to [Databricks AI/BI](https://docs.databricks.com/aws/en/dashboards/) (Dashboards and Genie).

## Overview

Migrating a BI estate to Databricks AI/BI typically involves more than recreating
visuals. It means mapping the source semantic layer to Unity Catalog, translating
calculated fields and measures to SQL / metric views, rebuilding dashboards and
report pages, and validating that the migrated output matches the original. The
projects in this directory provide reusable prompts, converters, and guidance to
accelerate that work.

## Projects

_Projects will be added here as they land. Each project lives in its own
sub-directory with a dedicated README covering setup and usage._

## Related work

Other AI/BI resources in this repository live under
[`data-warehousing`](../data-warehousing):

- [Power BI to AI/BI Converter](../data-warehousing/pbi-aibi-converter/) — a Streamlit
  app plus conversion/validation modules for migrating Power BI reports to Databricks AI/BI.
- [AI/BI Foundation](../data-warehousing/ai-bi-foundation/) — a reusable dashboard
  demo prompt template for Genie Code.
- [UC Business Semantics](../data-warehousing/dbrx-business-semantics/) — defining and
  governing business KPIs with Unity Catalog metric views.

## Contributing

New projects should follow the repository
[contribution guidelines](../CONTRIBUTING.md): a consistent naming convention and a
comprehensive README with installation and usage instructions.

## Disclaimer

⚠️ These resources are provided **as-is** for guidance and educational purposes. They
are **not** official Databricks tools or supported products, and Databricks support
channels do not cover them. Thoroughly test and validate all code in your own environment.
