# Customer 360 Lakehouse — Genie Agents with DABs, End to End

## The Story

| | |
|---|---|
| **Company** | Vela Cloud — B2B software company, 30,000 accounts |
| **Hero** | Maya Patel, VP of Customer Experience (owns support cost, renewal risk, exec reporting) |
| **Problem** | 3 weeks ago churn risk jumped to 3x normal — a $1.4M renewal is now at risk |
| **Investigation** | Maya compares regions in AI/BI, then asks Genie *"why is churn risk spiking?"* — traces it to delayed shipments driving a support-case surge |
| **Root cause** | A carrier/fulfillment slip in the **EMEA** region blew out order lead times; late orders spawned unresolved support cases, which spiked churn risk on the largest EMEA renewals |
| **Impact** | $1.4M renewal at risk, churn-risk index 3x normal (peaked ~3 weeks ago, still elevated), on-time delivery in EMEA dropped from ~92% to ~55% |

---

## Overview

Maya owns the number leadership actually watches: net renewal dollars. Three weeks ago her churn-risk index tripled and a $1.4M EMEA renewal lit up red. The problem: the answer lived in three disconnected reports — CRM accounts, the support queue, and the order/fulfillment feed — and nobody could stitch them together fast enough.

This demo tells the **end-to-end Customer 360 Lakehouse** story: synthetic CRM, case, and order feeds land through **Lakeflow Connect** with incremental ingestion and data-quality **expectations**, **Lakeflow Jobs** orchestrates the refresh into **Spark Declarative Pipelines** (Bronze → Silver → Gold) and governed **Metric Views**, and in **AI/BI** Maya compares regions, spots that delayed shipments are driving the support surge, and asks **Genie** which account segments are most exposed. **Genie One** lets her ask follow-up business questions in plain English; **Genie Code** helped the team build the governed KPI layer and dashboard faster. One governed customer view instead of three reports — analysis goes from days to minutes.

**Duration:** 6–8 minutes

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Accounts | 30,000 (CRM) |
| Regions | NA, EMEA, APAC, LATAM |
| Normal churn-risk index | ~1.0x baseline |
| Peak churn-risk index (~3 weeks ago) | ~3.0x (EMEA-led, still elevated) |
| Renewal at risk | $1.4M (top EMEA Enterprise accounts) |
| EMEA on-time delivery | ~92% → ~55% during the slip |
| Support case surge | EMEA unresolved cases ~3x baseline in the affected window |

---

## Demo Walkthrough

**Frame:** Monday exec review. Maya's renewal-risk tile is red and leadership wants an explanation, not three separate reports.

### Act 1 — Fresh, governed data (1–2 min)
Show the **Lakeflow Job** that orchestrates the run and the **SDP pipeline** graph: raw CRM/case/order feeds ingested incrementally (Auto Loader) with **expectations** dropping bad rows, flowing Bronze → Silver → Gold. Point at the **Metric Views** — churn-risk index, on-time delivery %, renewal-at-risk $ defined once, governed by **Unity Catalog**.

> *"Lakeflow Connect pulls CRM, support, and ERP with no custom plumbing. SDP shapes it into Gold with data-quality expectations enforced in the pipeline. Metric Views define the KPIs once so every consumer agrees on the number."*

### Act 2 — See it in AI/BI (2 min)
Open the **Customer 360** dashboard. The churn-risk trend spikes ~3 weeks ago; a region breakdown makes **EMEA** jump off the page. A second row lines up **on-time delivery** collapsing in EMEA against **unresolved cases** rising — same shape, same window.

> *"The 5-second test: churn risk tripled, and it's EMEA. Delayed shipments and the case surge move together."*

### Act 3 — Ask Genie why (2 min)
In the dashboard's **Genie** space, Maya types *"Which account segments are most exposed to the churn-risk spike?"* Genie returns EMEA **Enterprise** accounts up for renewal, with the **$1.4M** at-risk total. Follow-up: *"Show on-time delivery vs case volume for those accounts over the last 8 weeks."*

> *"Genie turns plain English into governed SQL over the same Metric Views — trusted answers, not a guess. **Genie One** is the front door for business users; **Genie Code** is how the team built this KPI layer and dashboard fast."*

### Closing
> One end-to-end Customer 360 Lakehouse: fresh incremental data with expectations, reusable governed KPIs, dashboards, and an agent-ready Genie space — all packaged as a Databricks Asset Bundle. Analysis went from days to minutes, and the $1.4M renewal now has an owner and a plan.

---

## Known limitations

These two limitations both come from the current `genie_spaces` DABs resource —
every other resource in this bundle is fully parameterized and deploys in one
shot.

**1. Deploy is a 3-phase flow, not one command.** The `genie_spaces` resource
**validates that its bound tables exist at deploy time**, but those tables are
*built by the setup job at run time*. A plain `bundle deploy` therefore fails on
the Genie space (its tables don't exist yet). The fix: deploy everything **except**
Genie, run the setup job to build the tables, then deploy again to add Genie —
see the 3-phase flow in **AGENTS.md** (and the CI/CD pipelines encode the same
three steps).

**2. The Genie space's table binding is static — edit the JSON before you deploy.**
`src/genie/genie_space.json` ships with placeholder table references
(`<your_catalog>.customer_360_demo.*`). **Before your first deploy, set the
`catalog` variable in `databricks.yml` (or pass `--var catalog=…`) AND edit the
`identifier` values in `src/genie/genie_space.json` to the same catalog** — the two
must agree or the Genie space's tables won't resolve. Both the `dev` and `prod`
targets deploy to that same catalog/schema — isolation is at the **workspace
level** (dev and prod are separate workspaces/metastores), not by using different
catalog/schema names, which is what keeps the single static binding valid in both.

The reason the binding can't be parameterized: the Databricks CLI deploys a
`genie_spaces` `file_path` JSON **verbatim** (no `${var.catalog}`/`${var.schema}`
substitution inside the file), and the `genie_spaces` resource has **no
`dataset_catalog`/`dataset_schema` field** to rebind tables per target — unlike
the `dashboards` resource, which does. So the JSON's `catalog.schema` must be
edited by hand whenever you change the `catalog`/`schema` variables.

## Products Showcased

| Product | Mode | What it does in this demo |
|---------|------|---------------------------|
| **Lakeflow Connect** | Talk track | Ingests CRM accounts, support cases, and orders with incremental (Auto Loader) ingestion — no custom pipelines |
| **SDP Pipeline** | Build | Bronze → Silver → Gold with data-quality expectations; produces the governed customer-360 Gold tables |
| **Lakeflow Jobs** | Build | Orchestrates the end-to-end refresh (data gen → pipeline) with retries and scheduling |
| **Metric Views** | Build | Governed KPI layer — churn-risk index, on-time delivery %, renewal-at-risk $ defined once, used by dashboard and Genie |
| **AI/BI Dashboard** | Build | The churn-risk spike and EMEA delivery collapse at a glance — the 5-second test |
| **AI/BI Genie** | Build | Answers *"which segments are most exposed?"* — natural language to governed SQL over the Metric Views |
| **Genie One** | Talk track | Business-user front door for plain-English follow-up questions |
| **Genie Code** | Talk track | How the team built the KPI layer and dashboard faster on the lakehouse |
| **Unity Catalog** | Talk track | One permission + lineage model across ingestion, pipeline, metrics, dashboard, and Genie |
