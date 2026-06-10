# Power BI to Databricks AI/BI Dashboard Conversion Guide

This guide documents the step-by-step process for converting a Power BI (.pbip) report into a Databricks AI/BI dashboard (.lvdash.json).

---

## Overview

| Concept | Power BI | Databricks AI/BI |
|---------|----------|------------------|
| File format | `.pbip` (project) / `.pbix` (package) | `.lvdash.json` |
| Data model | Semantic Model (TMDL) | SQL datasets (inline queries) |
| Visuals | Visual containers (JSON per visual) | Widgets (embedded in dashboard JSON) |
| Filters | Slicers (visual-level) | Filter widgets (global or page-level) |
| Relationships | Defined in `relationships.tmdl` | JOINs in SQL dataset queries |
| Measures | DAX expressions | SQL aggregations in widget field expressions |
| Layout | Pixel-based (x, y, width, height) | 6-column grid (x, y, width, height in grid units) |

---

## Step-by-Step Conversion Process

### Step 1: Parse the PBI Report Structure

A `.pbip` project has two main folders:

```
ReportName.pbip                          # Project file
ReportName.Report/                       # Report layer
  definition/
    report.json                          # Report metadata
    pages/
      pages.json                         # Page ordering
      <page-id>/
        page.json                        # Page display name, dimensions
        visuals/
          <visual-id>/visual.json        # Each visual definition
    version.json                         # Schema version
  StaticResources/                       # Themes, images
ReportName.SemanticModel/                # Data model layer
  definition/
    model.tmdl                           # Model config, table refs
    relationships.tmdl                   # Table relationships
    tables/
      <table_name>.tmdl                  # Column definitions + data source
    database.tmdl                        # Database metadata
```

**Key files to read:**
1. `model.tmdl` - Lists all tables referenced
2. `relationships.tmdl` - Shows how tables relate (foreign keys)
3. `tables/*.tmdl` - Column names, data types, and the data source connection string
4. `pages/pages.json` - Page ordering
5. `visuals/*/visual.json` - Each visual's type, fields, and aggregations

### Step 2: Extract the Data Source Information

Each `.tmdl` table file contains a `partition` block with the data source:

```
partition sales_transactions = m
    mode: directQuery
    source =
        let
            Source = DatabricksMultiCloud.Catalogs("host", "warehouse_path", ...),
            catalog_Database = Source{[Name="samples",Kind="Database"]}[Data],
            schema_Schema = catalog_Database{[Name="bakehouse",Kind="Schema"]}[Data],
            table_Table = schema_Schema{[Name="sales_transactions",Kind="Table"]}[Data]
        in
            table_Table
```

From this, extract:
- **Catalog**: `samples`
- **Schema**: `bakehouse`
- **Table**: `sales_transactions`
- **Fully-qualified name**: `samples.bakehouse.sales_transactions`

### Step 3: Map PBI Visual Types to AI/BI Widget Types

| PBI Visual Type | AI/BI Widget Type | Version | Notes |
|-----------------|-------------------|---------|-------|
| `textbox` | Text widget | N/A | Use `multilineTextboxSpec`, no `spec` block |
| `card` | `counter` | 2 | Map DAX aggregation to SQL |
| `slicer` (dropdown) | `filter-multi-select` | 2 | Place on global filter page |
| `slicer` (date range) | `filter-date-range-picker` | 2 | Use for date/timestamp fields |
| `lineChart` | `line` | 3 | Map Category to x, Y to y encoding |
| `barChart` / `clusteredBarChart` | `bar` | 3 | Map Category to x/y, Values to y/x |
| `donutChart` / `pieChart` | `pie` | 3 | Map Category to color, Y to angle |
| `pivotTable` / `table` | `table` | 2 | Preserve the tabular layout — always use a table widget, never a bar chart |
| `shape` | (skip) | - | Decorative elements have no equivalent |
| `map` / `filledMap` | (no equivalent) | - | Use a table with location data instead |

### Step 4: Map PBI Aggregation Functions to SQL

PBI uses numeric function codes in `Aggregation.Function`:

| PBI Function Code | PBI Name | SQL Equivalent | AI/BI Field Pattern |
|--------------------|----------|----------------|---------------------|
| 0 | Sum | `SUM(col)` | `{"name": "sum(col)", "expression": "SUM(\`col\`)"}` |
| 1 | Average | `AVG(col)` | `{"name": "avg(col)", "expression": "AVG(\`col\`)"}` |
| 2 | Count (non-null) | `COUNT(col)` | `{"name": "count(col)", "expression": "COUNT(\`col\`)"}` |
| 3 | Min | `MIN(col)` | `{"name": "min(col)", "expression": "MIN(\`col\`)"}` |
| 4 | Max | `MAX(col)` | `{"name": "max(col)", "expression": "MAX(\`col\`)"}` |
| 5 | CountNonNull (distinct) | `COUNT(DISTINCT col)` | `{"name": "countdistinct(col)", "expression": "COUNT(DISTINCT \`col\`)"}` |

> **For complex DAX patterns** (CALCULATE, DIVIDE, IF, SWITCH, time intelligence, VAR/RETURN, SELECTEDVALUE, iterator functions, ALL/ALLEXCEPT), see the **DAX TO SQL TRANSLATION GUIDE** for detailed side-by-side DAX → Spark SQL examples and placement rules.

> **IMPORTANT: Prefer custom calculations.** DAX measures should become widget-level `expression` fields (custom calculations) rather than derived columns in dataset SQL. This makes the measures visible and editable in the dashboard UI. Dataset SQL should only contain base tables, JOINs, CTEs for calculated tables, and window functions. Example: DAX `DIVIDE(SUM(Sales[Amount]), COUNTROWS(Sales))` becomes a widget field: `{"name": "avg_sale", "expression": "SUM(\`amount\`) / NULLIF(COUNT(*), 0)"}`.

### Step 5: Translate PBI Relationships to SQL JOINs

PBI relationships in `relationships.tmdl`:
```
relationship <id>
    fromColumn: sales_transactions.franchiseID
    toColumn: sales_franchises.franchiseID
```

Becomes a SQL JOIN in the dataset query:
```sql
FROM samples.bakehouse.sales_transactions t
JOIN samples.bakehouse.sales_franchises f ON t.franchiseID = f.franchiseID
```

**Key rules:**
- One-to-many relationships become `JOIN` (INNER JOIN by default)
- `crossFilteringBehavior: bothDirections` relationships may need special handling
- Include all columns needed by widgets and filters in the SELECT

### Step 6: Design AI/BI Datasets

Unlike PBI's semantic model where tables are separate and related, AI/BI dashboards use **flat SQL datasets**. Each dataset is a single SQL query that pre-joins all needed tables.

**Design principles:**
- One dataset per analytical domain (don't create one per visual)
- Include all dimension columns that filters will use
- Include all **base columns** that widget custom calculations will reference
- Use fully-qualified table names: `catalog.schema.table`
- **Keep datasets lean**: JOINs, WHERE clauses, CTEs for calculated tables, and window functions belong here. Avoid pre-computing aggregated measures — let widget custom calculations handle aggregations (SUM, COUNT, CASE WHEN, DIVIDE, etc.)

**Example:**
```json
{
  "name": "sales_overview",
  "displayName": "Sales Overview",
  "queryLines": [
    "SELECT ",
    "  t.transactionID, t.customerID, t.dateTime, ",
    "  t.product, t.quantity, t.totalPrice, ",
    "  f.name as franchise_name, ",
    "  f.country, f.city, f.district ",
    "FROM samples.bakehouse.sales_transactions t ",
    "JOIN samples.bakehouse.sales_franchises f ",
    "  ON t.franchiseID = f.franchiseID"
  ]
}
```

### Step 7: Convert Visuals to Widgets

#### Text / Title
PBI `textbox` visual with paragraph text becomes a text widget:
```json
{
  "widget": {
    "name": "title",
    "multilineTextboxSpec": {
      "lines": ["## Dashboard Title"]
    }
  },
  "position": {"x": 0, "y": 0, "width": 6, "height": 1}
}
```
- No `spec` block for text widgets
- Use markdown: `##` for h2, `###` for h3, `**bold**`
- **ONLY** create text widgets when the PBI report has an explicit `textbox` visual. NEVER invent or add text widgets (titles, subtitles, section headers) that don't exist in the source report.

#### Card -> Counter
PBI `card` with `CountNonNull(sales_transactions.customerID)` becomes:
```json
{
  "widget": {
    "name": "total-customers",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "sales_overview",
        "fields": [{"name": "countdistinct(customerID)", "expression": "COUNT(DISTINCT `customerID`)"}],
        "disaggregated": false
      }
    }],
    "spec": {
      "version": 2,
      "widgetType": "counter",
      "encodings": {
        "value": {"fieldName": "countdistinct(customerID)", "displayName": "Customers"}
      },
      "frame": {"showTitle": true, "title": "Customers"}
    }
  },
  "position": {"x": 0, "y": 2, "width": 2, "height": 3}
}
```

**Critical rule:** The `name` in fields must exactly match `fieldName` in encodings.

#### Slicer -> Filter Widget
PBI `slicer` on `sales_franchises.country` (dropdown) becomes:
```json
{
  "widget": {
    "name": "filter-country",
    "queries": [{
      "name": "sales_overview_country",
      "query": {
        "datasetName": "sales_overview",
        "fields": [{"name": "country", "expression": "`country`"}],
        "disaggregated": false
      }
    }],
    "spec": {
      "version": 2,
      "widgetType": "filter-multi-select",
      "encodings": {
        "fields": [{
          "fieldName": "country",
          "displayName": "Country",
          "queryName": "sales_overview_country"
        }]
      },
      "frame": {"showTitle": true, "title": "Country"}
    }
  },
  "position": {"x": 0, "y": 0, "width": 2, "height": 2}
}
```

Date slicers use `filter-date-range-picker` instead.

#### Donut Chart -> Pie Chart
PBI `donutChart` with Category=product, Y=SUM(quantity):
```json
{
  "widget": {
    "name": "sales-by-product",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "sales_overview",
        "fields": [
          {"name": "product", "expression": "`product`"},
          {"name": "sum(quantity)", "expression": "SUM(`quantity`)"}
        ],
        "disaggregated": false
      }
    }],
    "spec": {
      "version": 3,
      "widgetType": "pie",
      "encodings": {
        "color": {"fieldName": "product", "scale": {"type": "categorical"}, "displayName": "Product"},
        "angle": {"fieldName": "sum(quantity)", "scale": {"type": "quantitative"}, "displayName": "Total Quantity"}
      },
      "frame": {"showTitle": true, "title": "Sales by Product"}
    }
  },
  "position": {"x": 0, "y": 5, "width": 3, "height": 6}
}
```

#### Line Chart -> Line
PBI `lineChart` with Category=dateTime, Y=SUM(totalPrice):
```json
{
  "widget": {
    "name": "sales-over-time",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "sales_overview",
        "fields": [
          {"name": "daily(dateTime)", "expression": "DATE_TRUNC(\"DAY\", `dateTime`)"},
          {"name": "sum(totalPrice)", "expression": "SUM(`totalPrice`)"}
        ],
        "disaggregated": false
      }
    }],
    "spec": {
      "version": 3,
      "widgetType": "line",
      "encodings": {
        "x": {"fieldName": "daily(dateTime)", "scale": {"type": "temporal"}, "displayName": "Date"},
        "y": {"fieldName": "sum(totalPrice)", "scale": {"type": "quantitative"}, "displayName": "Sales (USD)"}
      },
      "frame": {"showTitle": true, "title": "Sales Over Time"}
    }
  },
  "position": {"x": 0, "y": 12, "width": 6, "height": 6}
}
```

### Step 8: Convert Layout from Pixels to Grid

PBI uses pixel coordinates on a 1280x720 canvas. AI/BI uses a 6-column grid.

**Conversion formula:**
- `grid_x = round(pbi_x / 1280 * 6)`
- `grid_width = round(pbi_width / 1280 * 6)` (minimum 1, snap to fill row = 6)

**Height mapping:** Derived proportionally from PBI pixel heights (12 grid rows per 720px canvas). Universal minimum of 2 (1 for text headers). No per-type maximums — the PBI designer's sizing choices are preserved.

**Width mapping:** Columns are distributed proportionally among visuals in each row based on their PBI pixel widths. This naturally gives wider PBI visuals more columns without hardcoded minimums.

**Column-skyline packing:** Each widget's y is determined by the tallest occupied cell in the columns it spans — NOT by the tallest widget in the whole row. Short widgets (filters, cards) stack tightly in their columns while taller widgets (charts, tables) span independently. This eliminates blank space below short items.

**Position enforcement:** After the LLM generates the dashboard, widget positions are programmatically overridden to match the blueprint. Phantom/duplicate widgets are removed.

### Step 9: Handle Filters

PBI slicers are placed directly on the page canvas. In AI/BI, you choose between:

| Filter Scope | Where to Place | Effect |
|-------------|----------------|--------|
| **Page-level** | On the same `PAGE_TYPE_CANVAS` page | Filters ONLY that page |
| **Global** | Dedicated page with `PAGE_TYPE_GLOBAL_FILTERS` | Filters ALL pages |

**Default behavior:** Convert PBI slicers to **page-level filter widgets** placed directly on their respective canvas page. This preserves the original PBI layout where slicers live alongside the visuals they filter.

**When to use global filters:** Only create a `PAGE_TYPE_GLOBAL_FILTERS` page when there are truly global slicers — i.e., in a multi-page report where the same slicer field appears on every page. In a single-page report, all slicers are always page-level.

### Step 10: Preserve Colors

PBI reports store colors in two places:
1. **Base theme** (`StaticResources/SharedResources/BaseThemes/*.json`) — contains the `dataColors` palette (array of hex strings) used by all charts in order
2. **Per-visual overrides** (`objects.dataPoint` in `visual.json`) — explicit color assignments for specific data points or series

To preserve colors in AI/BI:
- For charts with a categorical `color` encoding, add `scale.range` with hex colors from the PBI palette:
```json
"color": {
  "fieldName": "product",
  "scale": {"type": "categorical", "range": ["#118DFF", "#12239E", "#E66C37"]},
  "displayName": "Product"
}
```
- If specific category-to-color mappings are known, also include `scale.domain`:
```json
"color": {
  "fieldName": "region",
  "scale": {
    "type": "categorical",
    "domain": ["North", "South", "East"],
    "range": ["#118DFF", "#12239E", "#E66C37"]
  },
  "displayName": "Region"
}
```
- Use the first N colors from the palette (in order) where N is the expected number of distinct categories.

### Step 11: Test and Deploy

Before deploying, always:
1. **Test every dataset query** with `execute_sql()` to verify it returns data
2. **Verify column names** match what widgets reference
3. **Check cardinality** - pie/bar charts should have <=8 categories
4. Deploy with `create_or_update_dashboard()`
5. Publish for viewers with `publish_dashboard()`

---

## Common Pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| "Invalid widget definition" | Wrong `version` number | Counters/tables/filters: v2. Charts: v3 |
| "no selected fields to visualize" | Field name mismatch | `fields[].name` must exactly match `encodings.fieldName` |
| Blank widgets | No data or wrong `disaggregated` flag | Use `false` for aggregating, `true` for pre-aggregated |
| Text title and subtitle on same line | Multiple items in `lines[]` | Use separate text widgets at different y positions |
| Filter not working | Missing column in dataset | Ensure filter dimension exists in the dataset query |
| SQL errors | Using PBI/T-SQL syntax | Use Spark SQL (e.g., `date_sub()` not `DATEADD()`) |

---

## Reference: Visual Type Mapping

### PBI Query Structure

PBI visuals use a nested JSON structure for field references:
```json
{
  "field": {
    "Aggregation": {
      "Expression": {
        "Column": {
          "Expression": {"SourceRef": {"Entity": "table_name"}},
          "Property": "column_name"
        }
      },
      "Function": 0
    }
  }
}
```

Extract from this:
- **Table**: `Expression.SourceRef.Entity`
- **Column**: `Property`
- **Aggregation**: `Function` (0=SUM, 1=AVG, 2=COUNT, 3=MIN, 4=MAX, 5=COUNTDISTINCT)

### PBI Slicer Modes

| PBI Mode | AI/BI Widget Type |
|----------|-------------------|
| `'Dropdown'` | `filter-multi-select` |
| `'Between'` (date) | `filter-date-range-picker` |
| `'List'` | `filter-multi-select` |
| `'Before'` / `'After'` (date) | `filter-date-range-picker` |

---

## Example: Bakehouse Report Conversion

The `BakehouseSalesHighlights.lvdash.json` dashboard was converted from the Bakehouse PBI report. Here's the mapping:

| PBI Visual | Type | AI/BI Widget | Type |
|-----------|------|-------------|------|
| "Bakehouse Sales Highlights" | textbox | `title` | text |
| Rectangle banner | shape | (skipped) | - |
| Customers count | card | `total-customers` | counter v2 |
| Transactions count | card | `total-transactions` | counter v2 |
| (added) Revenue | - | `total-revenue` | counter v2 |
| Country slicer | slicer | `filter-country` | filter-multi-select v2 |
| City slicer | slicer | `filter-city` | filter-multi-select v2 |
| District slicer | slicer | `filter-district` | filter-multi-select v2 |
| Date slicer | slicer | `filter-date` | filter-date-range-picker v2 |
| Product donut | donutChart | `sales-by-product` | pie v3 |
| Franchise pivot table | pivotTable | `franchise-transactions` | table v2 |
| Sales line chart | lineChart | `sales-over-time` | line v3 |
