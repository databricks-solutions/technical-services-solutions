# Source Code Documentation

This document provides detailed documentation for the Python source files (Databricks notebooks) in the `src/` directory.

## Table of Contents

- [Overview](#overview)
- [export_genie_definition.ipynb](#export_genie_definitionpy)
- [deploy_genie_space.ipynb](#deploy_genie_spacepy)
- [Genie Space JSON Structure](#genie-space-json-structure)
- [API Reference](#api-reference)

---

## Overview

This project contains two Databricks notebooks that work together to provide CI/CD capabilities for Genie spaces:

| Notebook | Purpose | Databricks API |
|----------|---------|----------------|
| `export_genie_definition.ipynb` | Export a Genie space configuration from Dev | GET `/api/2.0/genie/spaces/{space_id}` |
| `deploy_genie_space.ipynb` | Deploy (create or update) a Genie space to Prod | POST/PATCH `/api/2.0/genie/spaces` |

### Notebook Format

These files use the **Databricks notebook source format** (indicated by `# Databricks notebook source` at the top). They can be:
- Run directly in Databricks notebooks
- Executed as part of Databricks Jobs
- Managed via Databricks Asset Bundles (DABs)

### Compute Configuration

By default, jobs run on **serverless compute**. This is the recommended option as it provides:
- Faster startup times
- No cluster management
- Cost-effective for short-running tasks

#### Alternative Compute Options

If serverless is not available or you need specific configurations, you can configure the following in `databricks.yml`:

**Option 1: Serverless (Default)**
```yaml
# No cluster configuration needed - serverless is used automatically
notebook_task:
  notebook_path: ./src/deploy_genie_space.ipynb
  # ... parameters ...
```

**Option 2: Existing Cluster**
```yaml
notebook_task:
  notebook_path: ./src/deploy_genie_space.ipynb
  # ... parameters ...
existing_cluster_id: "<YOUR_CLUSTER_ID>"
```

**Option 3: New Job Cluster**
```yaml
notebook_task:
  notebook_path: ./src/deploy_genie_space.ipynb
  # ... parameters ...
new_cluster:
  spark_version: "14.3.x-scala2.12"
  num_workers: 0
  node_type_id: "i3.xlarge"  # AWS: i3.xlarge, Azure: Standard_DS3_v2, GCP: n1-standard-4
  spark_conf:
    "spark.databricks.cluster.profile": "singleNode"
    "spark.master": "local[*]"
  custom_tags:
    "ResourceClass": "SingleNode"
```

### Dependencies

Both notebooks require the Databricks SDK:

```python
!pip install databricks-sdk -U
dbutils.library.restartPython()
```

---

## export_genie_definition.py

### Purpose

Exports a Genie space definition from a Databricks workspace and saves it as a JSON file. This is typically used to export from a Development workspace for version control and subsequent deployment to Production.

### Parameters (Widgets)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `space_id` | **Yes** | `""` | The Genie Space ID to export |
| `output_file` | Yes | `../genie_definition/genie_space_dev.json` | Path where the exported JSON will be saved |

### Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Validate Parameters                                               │
│    └─ Ensure space_id is provided                                   │
├─────────────────────────────────────────────────────────────────────┤
│ 2. Initialize Authentication                                         │
│    └─ Get workspace URL and PAT token from notebook context         │
├─────────────────────────────────────────────────────────────────────┤
│ 3. Call Get Space API                                                │
│    └─ GET /api/2.0/genie/spaces/{space_id}?include_serialized_space │
├─────────────────────────────────────────────────────────────────────┤
│ 4. Extract Serialized Space                                          │
│    └─ Parse JSON from serialized_space field                        │
├─────────────────────────────────────────────────────────────────────┤
│ 5. Save to File                                                      │
│    └─ Write formatted JSON to output_file                           │
├─────────────────────────────────────────────────────────────────────┤
│ 6. Return Output                                                     │
│    └─ Return status, space_id, title, output_file via dbutils.exit  │
└─────────────────────────────────────────────────────────────────────┘
```

### Code Sections

#### 1. Widget Parameters

```python
dbutils.widgets.text("space_id", "", "Space ID to export (required)")
dbutils.widgets.text("output_file", "../genie_definition/genie_space_dev.json", "Output JSON file path")
```

#### 2. Parameter Validation

```python
SPACE_ID = dbutils.widgets.get("space_id")
if not SPACE_ID:
    raise ValueError("space_id parameter is required.")
```

#### 3. Authentication

```python
w = WorkspaceClient()
workspace_url = w.config.host
pat_token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
```

The notebook uses the current notebook's authentication context to obtain:
- **workspace_url**: The Databricks workspace URL
- **pat_token**: Personal Access Token for API calls

#### 4. API Call

```python
response = requests.get(
    f"{workspace_url}/api/2.0/genie/spaces/{SPACE_ID}",
    headers=headers,
    params={"include_serialized_space": "true"}
)
```

The `include_serialized_space=true` parameter is critical - it returns the full space configuration.

### Output Format

The notebook returns a JSON object via `dbutils.notebook.exit()`:

```json
{
  "status": "exported",
  "space_id": "01f0fd2cfa1c16c185ec2ee3b4ea29d7", # your Genie space ID
  "title": "My Genie Space",
  "output_file": "../genie_definition/genie_space_dev.json"
}
```

### Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `ValueError: space_id parameter is required` | Missing space_id | Provide the space_id parameter |
| `requests.HTTPError` | API error (404, 403, etc.) | Check space_id and permissions |

---

## deploy_genie_space.py

### Purpose

Deploys a Genie space to a Databricks workspace. Can either:
- **Create** a new Genie space (if `space_id` is empty)
- **Update** an existing Genie space (if `space_id` is provided)

Optionally performs **catalog/schema replacement** to transform Dev references to Prod references.

### Parameters (Widgets)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `space_id` | No | `""` | Target Space ID. Empty = create new, filled = update |
| `input_file` | **Yes** | `../genie_definition/genie_space_dev.json` | Path to the source JSON file |
| `output_file` | No | Auto-generated | Path for the transformed JSON (Prod version) |
| `warehouse_id` | **Yes*** | `""` | SQL Warehouse ID (*required for create) |
| `title` | **Yes*** | `""` | Space title (*required for create) |
| `source_catalog` | No | `""` | Source catalog name to replace |
| `target_catalog` | No | `""` | Target catalog name |
| `source_schema` | No | `""` | Source schema name to replace |
| `target_schema` | No | `""` | Target schema name |

### Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Parse Parameters                                                  │
│    └─ Determine CREATE vs UPDATE mode based on space_id             │
├─────────────────────────────────────────────────────────────────────┤
│ 2. Validate Required Parameters                                      │
│    └─ For CREATE: warehouse_id and title required                   │
├─────────────────────────────────────────────────────────────────────┤
│ 3. Load Input JSON                                                   │
│    └─ Read the exported Genie space definition                      │
├─────────────────────────────────────────────────────────────────────┤
│ 4. Apply Catalog/Schema Replacement (if configured)                  │
│    └─ Transform all Unity Catalog references                        │
├─────────────────────────────────────────────────────────────────────┤
│ 5. Save Transformed JSON (optional)                                  │
│    └─ Write Prod version for audit trail                            │
├─────────────────────────────────────────────────────────────────────┤
│ 6. Deploy to Workspace                                               │
│    └─ POST (create) or PATCH (update) via Genie API                 │
├─────────────────────────────────────────────────────────────────────┤
│ 7. Return Output                                                     │
│    └─ Return status, space_id, title via dbutils.exit               │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Functions

#### `replace_catalog_schema(text, source_catalog, target_catalog, source_schema, target_schema)`

Replaces catalog and schema names in a text string. Handles both formats:

```python
# Input: "SELECT * FROM main_th.schema_dev.customers"
# Output: "SELECT * FROM main_prod.schema_prod.customers"

# Input: "SELECT * FROM `main_th`.`schema_dev`.`customers`"  
# Output: "SELECT * FROM `main_prod`.`schema_prod`.`customers`"
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `text` | str | The text to search and replace in |
| `source_catalog` | str | The catalog name to find |
| `target_catalog` | str | The catalog name to replace with |
| `source_schema` | str (optional) | The schema name to find |
| `target_schema` | str (optional) | The schema name to replace with |

**Returns:** `str` - The text with replacements applied

**Regex Patterns Used:**
```python
# Backtick-quoted format
rf'`{re.escape(source_catalog)}`\.`{re.escape(source_schema)}`\.'

# Plain format  
rf'\b{re.escape(source_catalog)}\.{re.escape(source_schema)}\.'
```

#### `update_genie_space_catalog(data, source_catalog, target_catalog, source_schema, target_schema)`

Updates all catalog/schema references in a Genie space JSON structure.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `data` | dict | The Genie space JSON as a Python dict |
| `source_catalog` | str | The catalog name to find |
| `target_catalog` | str | The catalog name to replace with |
| `source_schema` | str (optional) | The schema name to find |
| `target_schema` | str (optional) | The schema name to replace with |

**Returns:** `Tuple[dict, int]` - Updated data and count of replacements made

**JSON Paths Updated:**
| Path | Description |
|------|-------------|
| `data_sources.tables[].identifier` | Table identifiers |
| `data_sources.metric_views[].identifier` | Metric view identifiers |
| `instructions.example_question_sqls[].sql[]` | Example SQL queries |
| `benchmarks.questions[].answer[].content[]` | Benchmark answer content |

### Operation Modes

#### CREATE Mode (space_id is empty)

```python
payload = {
    "serialized_space": genie_space_json_str,
    "warehouse_id": WAREHOUSE_ID,
    "title": TITLE
}

response = requests.post(
    f"{workspace_url}/api/2.0/genie/spaces",
    headers=headers,
    data=json.dumps(payload)
)
```

**Requirements:**
- `warehouse_id` is **required**
- `title` is **required**

**Output includes the new space_id** - save this for future updates!

#### UPDATE Mode (space_id is provided)

```python
payload = {
    "serialized_space": genie_space_json_str
}
# Optional: title, warehouse_id overrides

response = requests.patch(
    f"{workspace_url}/api/2.0/genie/spaces/{SPACE_ID}",
    headers=headers,
    data=json.dumps(payload)
)
```

### Output Format

The notebook returns a JSON object via `dbutils.notebook.exit()`:

**For CREATE:**
```json
{
  "status": "created",
  "space_id": "01f0e034e6cb118695218a38adc4176d", # your Genie space ID
  "title": "My Genie Space Prod"
}
```

**For UPDATE:**
```json
{
  "status": "updated",
  "space_id": "01f0e034e6cb118695218a38adc4176d", # your Genie space ID
  "title": "My Genie Space Prod"
}
```

### Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `ValueError: warehouse_id is required` | Creating without warehouse_id | Provide warehouse_id parameter |
| `ValueError: title is required` | Creating without title | Provide title parameter |
| `requests.HTTPError: 404` | Space not found (update mode) | Verify space_id is correct |
| `requests.HTTPError: 403` | Permission denied | Check workspace permissions |

---

## Genie Space JSON Structure

The exported Genie space JSON follows this structure:

```json
{
  "version": 2,
  "config": {
    "sample_questions": [
      {
        "id": "unique-id",
        "question": ["Question text"]
      }
    ]
  },
  "data_sources": {
    "tables": [
      {
        "identifier": "catalog.schema.table_name",
        "column_configs": [
          {
            "column_name": "column_name",
            "enable_format_assistance": true,
            "enable_entity_matching": true
          }
        ]
      }
    ],
    "metric_views": [
      {
        "identifier": "catalog.schema.metric_view_name"
      }
    ]
  },
  "instructions": {
    "text_instructions": [
      {
        "id": "unique-id",
        "content": ["Instruction text..."]
      }
    ],
    "example_question_sqls": [
      {
        "id": "unique-id",
        "question": ["Question text"],
        "sql": ["SELECT...", "FROM...", "WHERE..."]
      }
    ]
  },
  "benchmarks": {
    "questions": [
      {
        "id": "unique-id",
        "question": ["Question text"],
        "answer": [
          {
            "format": "SQL",
            "content": ["SELECT...", "FROM...", "WHERE..."]
          }
        ]
      }
    ]
  }
}
```

### Key Fields

| Field | Description | Catalog Replacement |
|-------|-------------|---------------------|
| `data_sources.tables[].identifier` | Unity Catalog table reference | **Yes** |
| `data_sources.metric_views[].identifier` | Metric view reference | **Yes** |
| `instructions.example_question_sqls[].sql` | Example SQL queries | **Yes** |
| `benchmarks.questions[].answer[].content` | Benchmark answers | **Yes** |
| `config.sample_questions` | UI sample questions | No |
| `instructions.text_instructions` | Natural language instructions | No |

---

## API Reference

### Get Space (Export)

```
GET /api/2.0/genie/spaces/{space_id}
```

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `include_serialized_space` | boolean | Yes | Set to `true` to get full configuration |

**Response:**
```json
{
  "space_id": "string",
  "title": "string",
  "description": "string",
  "warehouse_id": "string",
  "serialized_space": "string (JSON)"
}
```

**Documentation:** [Get Space API](https://docs.databricks.com/api/workspace/genie/getspace)

### Create Space

```
POST /api/2.0/genie/spaces
```

**Request Body:**
```json
{
  "serialized_space": "string (JSON)",
  "warehouse_id": "string (required)",
  "title": "string (required)"
}
```

**Response:**
```json
{
  "space_id": "string",
  "title": "string"
}
```

**Documentation:** [Create Space API](https://docs.databricks.com/api/workspace/genie/createspace)

### Update Space

```
PATCH /api/2.0/genie/spaces/{space_id}
```

**Request Body:**
```json
{
  "serialized_space": "string (JSON)",
  "warehouse_id": "string (optional)",
  "title": "string (optional)"
}
```

**Response:**
```json
{
  "space_id": "string",
  "title": "string"
}
```

**Documentation:** [Update Space API](https://docs.databricks.com/api/workspace/genie/updatespace)

---

## Authentication

Both notebooks use the Databricks notebook context for authentication:

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
workspace_url = w.config.host

# Get PAT token from notebook context
pat_token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
```

This approach:
- Uses the same authentication as the notebook
- Works in Databricks Jobs
- No need to manage separate credentials
- Automatically uses the correct workspace URL
