```json
[
  {
    "name": "Customer 360 Lakehouse",
    "story": "Vela Cloud ingests CRM accounts, orders and support cases via Lakeflow Connect into a governed Spark Declarative Pipeline (bronze→silver→gold), orchestrated by Lakeflow Jobs. A governed Metric View defines the KPIs once, powering an AI/BI dashboard and a Genie Agent so Maya (VP Customer Experience) can spot the EMEA churn spike and ask follow-ups in plain language — reached through Genie One, all on the governed Databricks platform.",
    "columns": ["sources", "pipeline", "compute", "work", "entry"],
    "nodes": [
      { "id": "src-salesforce", "type": "source", "col": "sources", "row": 1, "label": "Salesforce", "icon": "file:vendor/salesforce", "desc": "CRM accounts, ARR, renewals" },
      { "id": "src-sap", "type": "source", "col": "sources", "row": 2, "label": "SAP", "icon": "file:vendor/sap", "desc": "Order & shipment data" },
      { "id": "src-zendesk", "type": "source", "col": "sources", "row": 3, "label": "Zendesk", "icon": "file:vendor/zendesk", "desc": "Support cases" },

      { "id": "lakeflow-genie-block", "type": "lakeflow-genie-block", "col": "pipeline", "row": 1 },
      { "id": "lakeflow-jobs", "type": "lakeflow-jobs", "col": "pipeline", "row": 2, "desc": "Scheduled orchestration: land → pipeline → refresh metrics", "note": "Orchestrates the pipeline nightly for the Monday exec review." },

      { "id": "sql-lakehouse", "type": "sql-lakehouse", "col": "compute", "row": 1 },
      { "id": "metric-views", "type": "metric-views", "col": "compute", "row": 2, "note": "mv_customer_health — governed KPI layer (churn index, on-time rate, ARR at risk) used by BOTH the dashboard and Genie so numbers match." },

      { "id": "ai-bi-dashboard", "type": "ai-bi-dashboard", "col": "work", "row": 1 },
      { "id": "genie", "type": "genie", "col": "work", "row": 2 },

      { "id": "genie-one", "type": "genie-one", "col": "entry", "rot": 90 },

      { "id": "db-platform", "type": "db-platform", "pin": { "at": "top-left", "to": "platform-box" } },
      { "id": "governance-block", "type": "governance-block", "pin": { "at": "top-right", "to": "platform-box" } },

      { "id": "platform-box", "type": "box", "z": -1,
        "wraps": ["src-salesforce", "src-sap", "src-zendesk", "lakeflow-genie-block", "lakeflow-jobs", "sql-lakehouse", "metric-views", "ai-bi-dashboard", "genie", "genie-one"] }
    ],
    "edges": [
      { "id": "e1", "from": "src-salesforce", "to": "lakeflow-genie-block@in-lakeflow-connect", "flow": true },
      { "id": "e2", "from": "src-sap", "to": "lakeflow-genie-block@in-lakeflow-connect", "flow": true },
      { "id": "e3", "from": "src-zendesk", "to": "lakeflow-genie-block@in-lakeflow-connect", "flow": true },

      { "id": "e4", "from": "lakeflow-jobs", "to": "lakeflow-genie-block", "arrow": "end", "dashed": true, "label": "orchestrates" },

      { "id": "e5", "from": "lakeflow-genie-block", "to": "sql-lakehouse", "flow": true },
      { "id": "e6", "from": "sql-lakehouse", "to": "metric-views", "flow": true },

      { "id": "e7", "from": "metric-views", "to": "ai-bi-dashboard", "flow": true },
      { "id": "e8", "from": "metric-views", "to": "genie", "flow": true },

      { "id": "e9", "from": "genie-one", "to": "ai-bi-dashboard" },
      { "id": "e10", "from": "genie-one", "to": "genie" }
    ]
  }
]
```
