# DAX to Spark SQL Translation Guide

This guide maps DAX measure patterns to their Spark SQL equivalents for use in AI/BI dashboard datasets and widget expressions (custom calculations).

**Placement rule — prefer custom calculations:**
- **Widget expressions (custom calculations)** are the preferred target. They appear in the dashboard UI under "+ Add custom calculation", making measures visible and editable. Widget expressions support any Spark SQL that is valid in a `SELECT ... GROUP BY` context: aggregations, arithmetic between aggregations, `CASE WHEN` inside aggregations, `NULLIF`, `COALESCE`, etc.
- **Dataset SQL** should contain only the base data: table JOINs, WHERE filters, CTEs for calculated tables, and columns referenced by widgets. Avoid pre-computing measures in the dataset SQL unless they require window functions (`OVER`), subqueries, or CTEs that cannot be expressed as a single `SELECT` expression.

**Examples of valid custom calculations:**
```
SUM(`amount`)
SUM(`amount`) / NULLIF(SUM(`quantity`), 0)
SUM(CASE WHEN `status` = 'Active' THEN `amount` ELSE 0 END)
COUNT(DISTINCT `customer_id`)
SUM(`current_year`) - SUM(`previous_year`)
ROUND(SUM(`revenue`) / NULLIF(SUM(`total_revenue`), 0) * 100, 2)
```

**Must stay in dataset SQL:**
```
-- Window functions
SUM(amount) OVER (PARTITION BY category)
-- CTEs / subqueries
WITH cte AS (SELECT ...) SELECT ...
-- JOINs between tables
SELECT ... FROM a JOIN b ON ...
```

---

## 1. Simple Aggregations

These translate directly to widget-level expressions.

| DAX | Spark SQL (widget expression) |
|-----|-------------------------------|
| `SUM(table[col])` | `SUM(\`col\`)` |
| `AVERAGE(table[col])` | `AVG(\`col\`)` |
| `COUNT(table[col])` | `COUNT(\`col\`)` |
| `COUNTROWS(table)` | `COUNT(*)` |
| `DISTINCTCOUNT(table[col])` | `COUNT(DISTINCT \`col\`)` |
| `MIN(table[col])` | `MIN(\`col\`)` |
| `MAX(table[col])` | `MAX(\`col\`)` |

---

## 2. DIVIDE

DAX `DIVIDE` returns an alternate result (default `BLANK()`) when the denominator is zero.

**DAX:**
```dax
DIVIDE([Total Sales], [Total Customers])
DIVIDE([Total Sales], [Total Customers], 0)
```

**Custom calculation (widget expression) — PREFERRED:**
```json
{"name": "sales_per_customer", "expression": "SUM(`amount`) / NULLIF(SUM(`customers`), 0)"}
```

**With explicit alternate result:**
```json
{"name": "sales_per_customer", "expression": "CASE WHEN SUM(`customers`) = 0 THEN 0 ELSE SUM(`amount`) / SUM(`customers`) END"}
```

---

## 3. IF / IIF

**DAX:**
```dax
IF([Total Sales] > 1000, "High", "Low")
```

**Custom calculation (widget expression):**
```json
{"name": "sales_tier", "expression": "CASE WHEN SUM(`amount`) > 1000 THEN 'High' ELSE 'Low' END"}
```

---

## 4. SWITCH

**DAX:**
```dax
SWITCH(
    [Region],
    "NA", "North America",
    "EU", "Europe",
    "APAC", "Asia Pacific",
    "Other"
)
```

**Dataset SQL** (best for dimension-level SWITCH on non-aggregated columns):
```sql
CASE region
    WHEN 'NA' THEN 'North America'
    WHEN 'EU' THEN 'Europe'
    WHEN 'APAC' THEN 'Asia Pacific'
    ELSE 'Other'
END AS region_name
```

**SWITCH with TRUE()** (common DAX pattern for range buckets):

**DAX:**
```dax
SWITCH(
    TRUE(),
    [Amount] > 1000, "Large",
    [Amount] > 100, "Medium",
    "Small"
)
```

**Custom calculation (widget expression):**
```json
{"name": "size_bucket", "expression": "CASE WHEN SUM(`amount`) > 1000 THEN 'Large' WHEN SUM(`amount`) > 100 THEN 'Medium' ELSE 'Small' END"}
```

---

## 5. CALCULATE with Filters

`CALCULATE` evaluates an expression under a modified filter context. Translate to conditional aggregation in a **custom calculation**.

### Simple filter

**DAX:**
```dax
CALCULATE(SUM(Sales[Amount]), Sales[Region] = "NA")
```

**Custom calculation (widget expression):**
```json
{"name": "na_sales", "expression": "SUM(CASE WHEN `region` = 'NA' THEN `amount` END)"}
```

### Multiple filters (AND)

**DAX:**
```dax
CALCULATE(SUM(Sales[Amount]), Sales[Region] = "NA", Sales[Year] = 2024)
```

**Custom calculation:**
```json
{"name": "na_sales_2024", "expression": "SUM(CASE WHEN `region` = 'NA' AND `year` = 2024 THEN `amount` END)"}
```

### CALCULATE with a table filter

**DAX:**
```dax
CALCULATE(SUM(Sales[Amount]), FILTER(ALL(Sales[Region]), Sales[Region] <> "Other"))
```

**Custom calculation:**
```json
{"name": "sales_excl_other", "expression": "SUM(CASE WHEN `region` <> 'Other' THEN `amount` END)"}
```

---

## 6. KEEPFILTERS / REMOVEFILTERS

These modify how CALCULATE interacts with existing filter context.

- **KEEPFILTERS**: Intersects the new filter with existing filters. In SQL this is the default behavior — a `WHERE` clause always intersects with other conditions. No special translation needed.
- **REMOVEFILTERS (or ALL as filter)**: Ignores filters on specified columns. In SQL, use an unfiltered aggregation or a subquery/window function.

**DAX:**
```dax
CALCULATE(SUM(Sales[Amount]), REMOVEFILTERS(Sales[Region]))
```

**Dataset SQL** (window functions must stay in dataset):
```sql
SUM(amount) OVER () AS total_amount_all_regions
```

**DAX:**
```dax
DIVIDE(
    SUM(Sales[Amount]),
    CALCULATE(SUM(Sales[Amount]), REMOVEFILTERS(Sales[Region]))
)
```

**Dataset SQL** (compute the grand total via window function):
```sql
SELECT *, SUM(amount) OVER () AS grand_total FROM catalog.schema.sales
```

**Custom calculation** (then reference both columns at widget level):
```json
{"name": "pct_of_total", "expression": "SUM(`amount`) / NULLIF(SUM(`grand_total`), 0)"}
```

---

## 7. SELECTEDVALUE

Returns the value of a column when the filter context has exactly one value. Commonly used in slicers and dynamic titles.

**DAX:**
```dax
SELECTEDVALUE(Calendar[Year])
```

**Translation:** In AI/BI dashboards, `SELECTEDVALUE` is handled by **filter widgets**. The slicer becomes a `filter-multi-select` or `filter-single-select` widget that filters the dataset automatically. You do not need to translate the `SELECTEDVALUE` call itself — the filter context is applied by the dashboard filter binding.

If `SELECTEDVALUE` is used inside a measure expression:

**DAX:**
```dax
CALCULATE(
    SUM(Sales[Amount]),
    Calendar[Year] = SELECTEDVALUE('Slicer Year'[Year])
)
```

**Spark SQL:** The filter widget handles year selection. The dataset just includes the year column, and the widget's filter binding applies the user's selection:
```sql
SELECT year, SUM(amount) AS total_amount
FROM catalog.schema.sales
GROUP BY year
```

---

## 8. TREATAS

Applies one table's values as filters on another table (virtual relationship).

**DAX:**
```dax
CALCULATE(
    SUM(Sales[Amount]),
    TREATAS(VALUES(DateSlicer[Date]), Calendar[Date])
)
```

**Spark SQL:** Translate to a `JOIN` or `WHERE IN` subquery:
```sql
SELECT s.amount
FROM catalog.schema.sales s
WHERE s.date IN (SELECT date FROM catalog.schema.date_slicer)
```

Or simply join the tables in the dataset and let filter widgets handle the filtering.

---

## 9. VAR / RETURN

DAX variables are intermediate computations. Translate to CTEs, subqueries, or inline expressions.

**DAX:**
```dax
VAR _total = SUM(Sales[Amount])
VAR _count = COUNTROWS(Sales)
RETURN DIVIDE(_total, _count, 0)
```

**Spark SQL (dataset column):**
```sql
SUM(amount) / NULLIF(COUNT(*), 0) AS avg_amount
```

**For more complex VAR chains, use a CTE:**
```sql
WITH base AS (
    SELECT
        region,
        SUM(amount) AS total,
        COUNT(*) AS cnt
    FROM catalog.schema.sales
    GROUP BY region
)
SELECT
    region,
    total,
    cnt,
    total / NULLIF(cnt, 0) AS avg_amount
FROM base
```

---

## 10. COALESCE / BLANK()

| DAX | Spark SQL |
|-----|-----------|
| `BLANK()` | `NULL` |
| `COALESCE(expr, 0)` | `COALESCE(expr, 0)` |
| `IF(ISBLANK(expr), 0, expr)` | `COALESCE(expr, 0)` |

---

## 11. RELATED

`RELATED` fetches a value from a related table (through a defined relationship). This is handled by `JOIN` in the dataset SQL.

**DAX:**
```dax
RELATED(Customers[CustomerName])
```

**Spark SQL:** Already resolved by the JOIN in the dataset:
```sql
SELECT s.*, c.customer_name
FROM catalog.schema.sales s
JOIN catalog.schema.customers c ON s.customer_id = c.customer_id
```

---

## 12. Time Intelligence

### Year-over-year comparison

**DAX:**
```dax
[Sales LY] = CALCULATE(SUM(Sales[Amount]), SAMEPERIODLASTYEAR(Calendar[Date]))
```

**Spark SQL (self-join approach):**
```sql
SELECT
    curr.month,
    curr.total AS sales_current,
    prev.total AS sales_last_year,
    (curr.total - prev.total) / NULLIF(prev.total, 0) AS yoy_change
FROM (
    SELECT date_trunc('MONTH', date) AS month, SUM(amount) AS total
    FROM catalog.schema.sales
    GROUP BY 1
) curr
LEFT JOIN (
    SELECT date_trunc('MONTH', date) AS month, SUM(amount) AS total
    FROM catalog.schema.sales
    GROUP BY 1
) prev ON curr.month = add_months(prev.month, 12)
```

**Spark SQL (window function approach):**
```sql
SELECT
    date_trunc('MONTH', date) AS month,
    SUM(amount) AS sales_current,
    LAG(SUM(amount), 12) OVER (ORDER BY date_trunc('MONTH', date)) AS sales_last_year
FROM catalog.schema.sales
GROUP BY 1
```

### Period-to-date (YTD, MTD, QTD)

**DAX:**
```dax
[YTD Sales] = TOTALYTD(SUM(Sales[Amount]), Calendar[Date])
```

**Spark SQL:**
```sql
SUM(amount) OVER (
    PARTITION BY YEAR(date)
    ORDER BY date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) AS ytd_sales
```

Or in a grouped dataset:
```sql
SELECT
    date,
    SUM(SUM(amount)) OVER (
        PARTITION BY YEAR(date)
        ORDER BY date
    ) AS ytd_sales
FROM catalog.schema.sales
GROUP BY date
```

### DATEADD / DATESINPERIOD

**DAX:**
```dax
CALCULATE(SUM(Sales[Amount]), DATEADD(Calendar[Date], -1, YEAR))
```

**Spark SQL:**
```sql
SUM(CASE WHEN date BETWEEN add_months(current_date(), -12) AND current_date() THEN amount END) AS rolling_12m_sales
```

---

## 13. Iterator Functions (SUMX, AVERAGEX, MAXX, etc.)

DAX iterators evaluate an expression row-by-row then aggregate. In SQL, the row-level expression goes inside the aggregation function.

**DAX:**
```dax
SUMX(Sales, Sales[Quantity] * Sales[UnitPrice])
```

**Spark SQL:**
```sql
SUM(quantity * unit_price) AS total_revenue
```

**DAX:**
```dax
AVERAGEX(Products, Products[Price] * (1 - Products[Discount]))
```

**Spark SQL:**
```sql
AVG(price * (1 - discount)) AS avg_net_price
```

---

## 14. ALL / ALLEXCEPT

`ALL` removes all filters from a table or column. `ALLEXCEPT` removes all filters except the specified columns.

### ALL for percentage of total

**DAX:**
```dax
DIVIDE(SUM(Sales[Amount]), CALCULATE(SUM(Sales[Amount]), ALL(Sales)))
```

**Spark SQL (window function):**
```sql
SUM(amount) AS segment_sales,
SUM(amount) / SUM(SUM(amount)) OVER () AS pct_of_total
```

### ALLEXCEPT for subtotals

**DAX:**
```dax
CALCULATE(SUM(Sales[Amount]), ALLEXCEPT(Sales, Sales[Region]))
```

**Spark SQL (window function):**
```sql
SUM(amount) OVER (PARTITION BY region) AS region_total
```

---

## 15. FORMAT / Text Functions

| DAX | Spark SQL |
|-----|-----------|
| `FORMAT(value, "0.0%")` | `CONCAT(ROUND(value * 100, 1), '%')` |
| `FORMAT(date, "YYYY-MM")` | `date_format(date, 'yyyy-MM')` |
| `CONCATENATE(a, b)` | `CONCAT(a, b)` |
| `LEFT(text, n)` | `LEFT(text, n)` |
| `RIGHT(text, n)` | `RIGHT(text, n)` |
| `LEN(text)` | `LENGTH(text)` |
| `UPPER(text)` | `UPPER(text)` |
| `LOWER(text)` | `LOWER(text)` |
| `TRIM(text)` | `TRIM(text)` |

---

## 16. DAX Calculated Tables → SQL

PBI calculated tables (`.tmdl` files with `partition ... = calculated`) are virtual tables defined via DAX table expressions. They have **no external data source** — they derive from other tables in the model. Translate them to SQL subqueries or CTEs in the dataset.

### DISTINCT + SELECTCOLUMNS → SELECT DISTINCT

The most common pattern: project and deduplicate columns from an existing table.

**DAX:**
```dax
DISTINCT(
    SELECTCOLUMNS(
        'd_calendario',
        "dt_referencia", 'd_calendario'[dt_fim_mes],
        "nm_mes", 'd_calendario'[nm_mes_ano_abreviado],
        "idx", d_calendario[idx_ano_mes]
    )
)
```

**Spark SQL:**
```sql
SELECT DISTINCT
    dt_fim_mes AS dt_referencia,
    nm_mes_ano_abreviado AS nm_mes,
    idx_ano_mes AS idx
FROM catalog.schema.d_calendario
```

### DATATABLE → VALUES / UNION ALL

Hardcoded lookup tables.

**DAX:**
```dax
DATATABLE(
    "Período", STRING,
    {
        {"Período 1"},
        {"Período 2"}
    }
)
```

**Spark SQL:**
```sql
SELECT 'Período 1' AS periodo
UNION ALL
SELECT 'Período 2' AS periodo
```

For multi-column DATATABLE:
```dax
DATATABLE("Status", STRING, "Code", INTEGER, {{"Active", 1}, {"Inactive", 0}})
```
```sql
SELECT 'Active' AS status, 1 AS code
UNION ALL
SELECT 'Inactive', 0
```

### FILTER → WHERE

**DAX:**
```dax
FILTER('sales', 'sales'[region] = "LATAM")
```

**Spark SQL:**
```sql
SELECT * FROM catalog.schema.sales WHERE region = 'LATAM'
```

### ADDCOLUMNS → SELECT with expressions

**DAX:**
```dax
ADDCOLUMNS('orders', "year", YEAR('orders'[order_date]), "is_large", 'orders'[amount] > 1000)
```

**Spark SQL:**
```sql
SELECT *, YEAR(order_date) AS year, amount > 1000 AS is_large
FROM catalog.schema.orders
```

### SUMMARIZE → GROUP BY

**DAX:**
```dax
SUMMARIZE('sales', 'sales'[product], "total", SUM('sales'[amount]))
```

**Spark SQL:**
```sql
SELECT product, SUM(amount) AS total
FROM catalog.schema.sales
GROUP BY product
```

### CALENDAR / CALENDARAUTO → EXPLODE + SEQUENCE

**DAX:**
```dax
CALENDAR(DATE(2020, 1, 1), DATE(2025, 12, 31))
```

**Spark SQL:**
```sql
SELECT EXPLODE(SEQUENCE(DATE '2020-01-01', DATE '2025-12-31', INTERVAL 1 DAY)) AS date
```

### UNION → UNION ALL

**DAX:**
```dax
UNION('table_a', 'table_b')
```

**Spark SQL:**
```sql
SELECT * FROM catalog.schema.table_a
UNION ALL
SELECT * FROM catalog.schema.table_b
```

### CROSSJOIN → CROSS JOIN

**DAX:**
```dax
CROSSJOIN('dim_region', 'dim_product')
```

**Spark SQL:**
```sql
SELECT * FROM catalog.schema.dim_region
CROSS JOIN catalog.schema.dim_product
```

### TOPN → ORDER BY + LIMIT

**DAX:**
```dax
TOPN(10, 'sales', 'sales'[amount], DESC)
```

**Spark SQL:**
```sql
SELECT * FROM catalog.schema.sales ORDER BY amount DESC LIMIT 10
```

### EXCEPT / INTERSECT

**DAX:**
```dax
EXCEPT('all_customers', 'active_customers')
INTERSECT('set_a', 'set_b')
```

**Spark SQL:**
```sql
SELECT * FROM catalog.schema.all_customers EXCEPT SELECT * FROM catalog.schema.active_customers
SELECT * FROM catalog.schema.set_a INTERSECT SELECT * FROM catalog.schema.set_b
```

### ROW → Single-row SELECT

**DAX:**
```dax
ROW("label", "Total", "value", 0)
```

**Spark SQL:**
```sql
SELECT 'Total' AS label, 0 AS value
```

### Placement rule for calculated tables

| Usage in PBI | Placement in AI/BI |
|---|---|
| Calculated table used as a **slicer source** | Inline subquery or CTE in the dataset that feeds the filter widget |
| Calculated table used in **measures / visuals** | CTE in the dataset SQL, then reference in the main query |
| Calculated table used only for **relationships** | Translate to a `JOIN` — no separate dataset needed |
| Hardcoded lookup (`DATATABLE`) | Inline `UNION ALL` values inside a CTE |

**Example — calculated slicer table as CTE:**
```sql
WITH period_slicer AS (
    SELECT DISTINCT
        dt_fim_mes AS dt_referencia,
        nm_mes_ano_abreviado,
        idx_ano_mes
    FROM catalog.schema.d_calendario
)
SELECT * FROM period_slicer ORDER BY idx_ano_mes
```

---

## 17. Placement Summary

**Prefer custom calculations (widget expressions)** for all DAX measures. Keep dataset SQL lean — only base tables, JOINs, CTEs, and window functions.

| DAX Pattern | Where in AI/BI | How |
|-------------|----------------|-----|
| Simple `SUM`, `COUNT`, `AVG`, `MIN`, `MAX` | **Custom calculation** | `SUM(\`col\`)` |
| `DIVIDE` | **Custom calculation** | `SUM(\`a\`) / NULLIF(SUM(\`b\`), 0)` |
| `IF`, `SWITCH` on aggregates | **Custom calculation** | `CASE WHEN SUM(\`col\`) > X THEN ... END` |
| `CALCULATE` with filters | **Custom calculation** | `SUM(CASE WHEN \`col\` = 'X' THEN \`amount\` END)` |
| `SELECTEDVALUE` | Filter widget | Handled by filter binding |
| `RELATED` | Dataset SQL | Already in `JOIN` |
| `VAR / RETURN` (simple) | **Custom calculation** | Inline the expression |
| `VAR / RETURN` (complex, CTE) | Dataset SQL | CTE in dataset query |
| `SUMX`, `AVERAGEX` | **Custom calculation** | `SUM(\`expr\`)`, `AVG(\`expr\`)` |
| `ALL` / percentage of total | Dataset SQL + custom calc | Window `SUM() OVER ()` in dataset, ratio in custom calc |
| Time intelligence (YoY, YTD) | Dataset SQL | Window functions, self-join, or `add_months` |
| Formatting (`FORMAT`) | **Custom calculation** or dataset | `ROUND(...)`, `CONCAT(...)` |
| Calculated table (slicer source) | Dataset SQL | CTE or subquery feeding filter widget |
| Calculated table (used in visuals) | Dataset SQL | CTE joined into main query |
| `DATATABLE` (hardcoded lookup) | Dataset SQL | Inline `UNION ALL` values in CTE |

**Rule of thumb:** If the DAX measure can be written as a single expression over dataset columns (using aggregations, CASE WHEN, arithmetic), make it a **custom calculation**. If it needs window functions, subqueries, or CTEs, put it in the **dataset SQL**.
