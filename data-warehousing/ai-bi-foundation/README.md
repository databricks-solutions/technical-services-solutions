# AI/BI Foundation

A reusable **AI/BI dashboard demo prompt template** for Genie Code. Point it at a
customer's gold tables and it explores the schemas, identifies key metrics and
dimensions, and builds a multi-page dashboard end-to-end.

## Contents

- [`aibi-dashboard-demo-prompt.md`](./aibi-dashboard-demo-prompt.md) — the prompt
  template plus usage and customization notes.

## Usage

1. Open [`aibi-dashboard-demo-prompt.md`](./aibi-dashboard-demo-prompt.md).
2. Replace the `<catalog>.<schema>.<table_A/B/C>` placeholders with the customer's
   actual gold table names.
3. Paste the prompt into Genie Code on a new or existing dashboard. Genie Code will
   explore the tables, generate SQL, and build the dashboard (Executive Summary,
   Detailed Breakdown, Cross-Table Analysis, and a drill-down Data Table).

See the prompt file for customization tips (extra pages, specific metrics, join keys,
filters and parameters).

## Disclaimer

**Databricks support doesn't cover this content.** For questions or bugs, open a
GitHub issue; the repo maintainers help on a best-effort basis.

These resources are provided **as-is** for guidance and educational purposes. They
are **not official Databricks tools** or supported products, and represent
implementation examples and best-practice guidance. Users should thoroughly test and
validate all content in their specific environments.
