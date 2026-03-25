# Genie Space CI/CD

Promote Databricks AI/BI Genie spaces from Dev to Prod. The pipeline exports a Genie space definition, replaces Unity Catalog references (catalog/schema), and deploys it to a target workspace -- all orchestrated via Databricks Asset Bundles.

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  Dev Workspace    │      │  Git / CI-CD     │      │  Prod Workspace  │
│                   │      │                  │      │                  │
│  Genie Space ─────┼──►───│  genie_space.json│──►───┼──► Genie Space  │
│  (source catalog) │      │                  │      │  (target catalog)│
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

## Folder Structure

```
genie-cicd/
├── databricks.yml.template                     # DAB configuration template -- copy to databricks.yml
├── src/
│   ├── export_genie_definition.ipynb           # Exports a Genie space to JSON via API
│   └── deploy_genie_space.ipynb                # Deploys JSON to a workspace (create or update)
└── genie_definition/
    └── examples/
        ├── genie_space_dev.json                # Example: what an exported Dev definition looks like
        └── genie_space_prod.json               # Example: same definition after catalog/schema replacement
```

> **Note:** The JSON files under `genie_definition/examples/` are reference samples showing the Genie space JSON structure before and after catalog/schema replacement. They are **not meant to be run** -- they point to tables that don't exist in your workspace. When you run the pipeline, it will export your own Genie space and write the files to `genie_definition/`.

## Prerequisites

- **Databricks CLI** v0.200+ ([install guide](https://docs.databricks.com/dev-tools/cli/install.html))
- **A Genie space in Dev** that you want to promote to Prod
- **Permissions**: `CAN EDIT` on the source Genie space, `CAN MANAGE` on the target workspace
- **SQL Warehouse** running in the target workspace

Verify your CLI setup:

```bash
databricks --version        # v0.200+
databricks workspace list / # confirms auth works
```

## Quick Start

### Step 1 -- Gather your IDs

You need three things before starting:

| What | Where to find it |
|------|------------------|
| **Dev Genie Space ID** | URL when viewing the space: `.../genie/spaces/{SPACE_ID}` |
| **Prod SQL Warehouse ID** | SQL Warehouses page: `.../sql/warehouses/{WAREHOUSE_ID}` |
| **Workspace URLs** | Browser URL when logged in to each workspace |

### Step 2 -- Create your `databricks.yml`

```bash
cp databricks.yml.template databricks.yml
```

Open `databricks.yml` and fill in every `<TODO>` placeholder:

| Variable | What to set |
|----------|-------------|
| `dev_space_id` | Your Dev Genie Space ID |
| `prod_space_id` | Leave `""` for the first run |
| `prod_warehouse_id` | Your Prod SQL Warehouse ID |
| `genie_space_title` | Title for the Prod space |
| `source_catalog` / `source_schema` | Dev catalog and schema names |
| `target_catalog` / `target_schema` | Prod catalog and schema names |
| `targets.dev.workspace.host` | Dev workspace URL |
| `targets.prod.workspace.host` | Prod workspace URL |

### Step 3 -- Deploy and run

```bash
databricks bundle validate --target prod
databricks bundle deploy --target prod
databricks bundle run promote_genie_to_prod --target prod
```

This runs two tasks:
1. **Export** -- calls the Genie API to export your Dev space to `genie_definition/genie_space_dev.json`
2. **Deploy** -- replaces catalog/schema references and creates a new Prod Genie space

### Step 4 -- Save the Prod Space ID

The deploy task output will print:

```
⚠️  IMPORTANT: Save this Space ID for future updates:
   space_id = "01f0e034e6cb118695218a38adc4176d"
```

Paste it into your `databricks.yml`:

```yaml
prod_space_id:
  default: "01f0e034e6cb118695218a38adc4176d"
```

From now on, running the pipeline again will **update** the existing Prod space instead of creating a new one:

```bash
databricks bundle deploy --target prod
databricks bundle run promote_genie_to_prod --target prod
```

---

## How catalog/schema replacement works

The deploy notebook scans the Genie space JSON and replaces all Unity Catalog references from source to target. Both plain and backtick-quoted identifiers are handled:

| Before | After |
|--------|-------|
| `main_th.schema_dev.customers` | `main_prod.schema_prod.customers` |
| `` `main_th`.`schema_dev`.`customers` `` | `` `main_prod`.`schema_prod`.`customers` `` |

Replacements are applied to:
- `data_sources.tables[].identifier`
- `data_sources.metric_views[].identifier`
- `instructions.example_question_sqls[].sql[]`
- `benchmarks.questions[].answer[].content[]`

---

## Exporting a Genie space manually

If you need to export a Genie space outside of the pipeline (e.g. to check it into Git), run `src/export_genie_definition.ipynb` directly with these widget values:

| Widget | Value |
|--------|-------|
| `space_id` | The Genie Space ID to export |
| `output_file` | Where to save the JSON (default: `../genie_definition/genie_space.json`) |

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `space_id parameter is required` | Set `dev_space_id` in `databricks.yml` |
| `warehouse_id is required` | Set `prod_warehouse_id` in `databricks.yml` |
| `title is required` | Set `genie_space_title` in `databricks.yml` |
| `Unable to register space` / `500 Internal Server Error` | The title likely contains a `/` character. Genie space names cannot include `/` -- use `CICD` instead of `CI/CD` |
| `Display name cannot contain a '/'` | Same as above -- remove `/` from `genie_space_title` |
| `Permission denied` | You need `CAN EDIT` on the source space and `CAN MANAGE` on the target workspace |
| `Space not found` | Verify the space ID exists and is accessible |
| `Serverless not available` | Set `existing_cluster_id` or `new_cluster` in `databricks.yml` (see comments in template) |
