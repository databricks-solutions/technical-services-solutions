# Genie

Solutions and accelerators for building and operating Databricks Genie spaces. This track covers natural-language data exploration, Genie space setup, and administration patterns.

## Structure

```
genie/
└── genie-helpers/   # Standalone notebooks for operating, monitoring & governing Genie spaces
```

## Projects

### [genie-helpers](./genie-helpers)

A collection of standalone, widget-driven notebooks for operating, monitoring, and governing Genie spaces:

- **Manage Genie Space Permissions** — administer Genie space access via the Permissions API
- **Genie Conversation History Ingestion** — incrementally ingest conversations & messages to a Delta table, plus popular-question and AI topic-clustering analytics
- **Genie Feedback Extraction** — incrementally extract POSITIVE/NEGATIVE user feedback
- **Genie Reasoning Process Logger** — log the full step-by-step Genie reasoning process (reasoning, SQL, results, final answer)
- **Genie Space Conversation Duration Logger** — capture per-message latency with a three-stage timing breakdown
- **UC Governance Explorer – Tags, Comments & Lineage** — explore Unity Catalog tags, comments & lineage to prepare data for Genie
- **LLM Column Comment Generator** — auto-generate missing column comments with an LLM via `ai_query`

See [genie-helpers/README.md](./genie-helpers/README.md) for per-notebook details.
