# AI/BI Dashboard Demo Prompt Template

A reusable Genie Code prompt for creating AI/BI dashboards on a customer environment. Replace the placeholder table names with the customer's actual gold tables.

---

## Prompt

```
I want to create an AI/BI dashboard using the following gold tables:

- `<catalog>.<schema>.<table_A>`
- `<catalog>.<schema>.<table_B>`
- `<catalog>.<schema>.<table_C>`

Please do the following:

1. **Explore the tables** — read the schema, column descriptions, and
   sample data from each table to understand what's available.

2. **Identify key metrics and dimensions** — based on the table schemas,
   suggest the most meaningful KPIs (e.g. counts, sums, averages,
   rates) and the best dimensions to slice them by (e.g. time periods,
   categories, regions, statuses).

3. **Create a dashboard** with the following pages/sections:
   - **Executive Summary** — top-level KPIs as counter widgets and a
     trend line over time.
   - **Detailed Breakdown** — bar/column charts breaking down the
     primary metric by the most relevant dimensions.
   - **Cross-Table Analysis** — at least one widget that joins two or
     more of the tables above to show a relationship or enriched view.
   - **Data Table** — a detail table widget for drill-down exploration.

4. Apply a clean, professional layout with descriptive widget titles
   and axis labels.

Assume the audience is a business stakeholder who wants to monitor
these datasets at a glance.
```

---

## Usage Instructions

1. Replace `<catalog>.<schema>.<table_A/B/C>` with the customer's actual gold table names.
2. Paste the prompt into Genie Code on any page (or directly on a new dashboard).
3. Genie Code will explore the tables, generate SQL, and build the dashboard end-to-end.

## Customization Tips

- Add or remove sections (e.g. add a "Trends and Forecasting" page if the data has time-series columns).
- Specify exact metrics if known (e.g. "revenue", "order count", "churn rate") to make the output more targeted.
- Mention specific join keys if the tables have non-obvious relationships.
- For larger demos, add a fifth section: **Filters and Parameters** — request date-range filters, dropdown selectors for key dimensions, etc.
