# UC Semantics Migration Map

> **⚠️ BETA — still being tested.** This skill is under active development and has not yet been validated against real customer estates or a live Tableau / Power BI MCP connection. Behavior, file formats and the Pages/Wikis APIs it relies on may change. Review every plan and generated Metric View before approving writes, and try it in a non-production workspace first.

Build a governed **Unity Catalog semantic foundation** from a customer's BI estate. The skill reads
Tableau / Power BI files (or a live Tableau / Power BI MCP connection) plus any documentation,
finds the business concepts that need one consolidated definition (Net Revenue, Active Customers…),
and designs — then, once a person approves it, creates — the Domains, Subdomains, Metric Views,
Pages and Wikis that hold them.

It runs as a **Genie Code skill**: the user converses, the agent runs the scripts.

## Two stages, one human gate

| Stage | What happens | Writes? |
|---|---|---|
| **1 · Assessment** | Ingest inputs → find concepts and their competing definitions → propose domains, Metric View *shells*, Pages and Wikis → render a self-contained `report.html` and review it in chat. No Metric View YAML is written here. | No (read-only) |
| **Human gate** | The user decides which definition wins, which objects get created, and approves the plan. | — |
| **2 · Implementation** | The agent authors each Metric View's YAML on the real columns, following the live [`uc-semantics-patterns`](https://github.com/databricks-solutions/uc-semantics-patterns) repo; validates it on a throw-away view; the user approves the YAML; only approved objects are applied. | Yes, only after an explicit go |

Both stages are **re-runnable**. Decisions, hand edits and approvals survive a refresh, and applying
the same map twice is a no-op.

## What it creates

- **Domains / subdomains** (governed-tag-backed, account level)
- **Metric Views** (YAML v1.1) with domain tags
- **Pages** and **Wikis** (Beta)

See [`references/uc-objects.md`](references/uc-objects.md) for each object's API, privileges and limits.

## Safety properties

- Dry-run by default; writes need `--execute --yes`.
- Objects are created as drafts unless `--publish` is passed.
- `--prune` only touches objects the tool itself created (tracked in `apply-state.json`); `--adopt` is
  required to take over anything it did not create.
- A tag prefix keeps its objects separate in shared accounts.

## Privileges

| Object | Needs |
|---|---|
| Metric Views | `USE CATALOG`, `USE SCHEMA`, `CREATE TABLE` (create view) on the target schema, `SELECT` on sources, a SQL warehouse |
| Governed tags | Permission to create governed tags (account admin) |
| Domains | `MANAGE DISCOVER` (account and workspace admins by default) |
| Pages / Wikis | `MANAGE PAGES` (all account users by default); publishing needs Page Manager or domain admin |

Assessment needs none of these: it reads only the files you give it.

## Install (Genie Code)

Add a Git folder for `technical-services-solutions` under
`/Workspace/Users/<your-email>/.assistant/`, enable **Sparse Checkout**, and set the cone pattern to
`aibi-migration/uc-semantics-migration-map` (or download the
[`uc-semantics-migration-map-latest`](https://github.com/databricks-solutions/technical-services-solutions/releases/tag/uc-semantics-migration-map-latest)
release zip). See [Installing a skill](https://docs.databricks.com/aws/en/genie-code/skills).

Then open Genie Code and ask, for example:

> *Build a UC semantics migration map for the Tableau workbooks in `/Volumes/<catalog>/<schema>/<volume>`.*

`SKILL.md` is the operating guide the agent follows.

## Verify the tooling (no workspace needed)

```bash
pip install -r requirements.txt
python3 -I tests/test_idempotency.py
```

`tests/live_smoke.py` runs the same contract end to end against a real workspace; it creates and
removes a throw-away schema (and, with `--account-objects`, governed tags, domains, pages and wikis
under a random prefix).

## Known limits

- A UI edit to a Metric View whose recorded hash still matches is not detected.
- Domain display names and Discover-page sections are UI-only.
- Pages and Wikis are Beta APIs and may change.
- Verified against synthetic estates and live workspaces on AWS and Azure; a live Tableau / Power BI
  MCP connection has not yet been exercised end to end.

## Layout

`SKILL.md` · `scripts/` · `references/` · `templates/report_template.html` · `examples/` (synthetic
"Acme Retail") · `tests/`
