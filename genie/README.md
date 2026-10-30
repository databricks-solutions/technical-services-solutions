# Genie

Solutions and accelerators for building, operating, and optimizing Databricks
Genie spaces. This track covers natural-language data exploration, Genie space
setup, administration patterns, and agent quality/optimization.

## Projects

### [Genie Agent Optimization](./genie-agent-optimization/)

Patterns and tooling to measure and improve Genie agent quality — evaluation
sets, instruction/example tuning, and semantic-layer curation (metric views,
synonyms, descriptions).

### [Genie Agent Scanner](./genie-agent-scanner/)

A portable Agent Skill (`genie-agent-scan-optimize`) that audits a single Genie
space/agent with a deterministic 12-check "IQ scan", scores it 0–12 with a
maturity tier, and then guides approval-gated context fixes through the Genie
REST API — a lightweight, local alternative to the Genie Workbench app. Runs in
Genie Code, Claude Code, and Cursor.
