# Databricks notebook source
"""
Deploy the governed Metric View `mv_customer_health`.

Metric views have no PySpark API — this notebook runs the
`CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML` SQL inline, with the
catalog/schema resolved from base_parameters (so every task uses the same
values). Source: gold_daily_health (built by the SDP pipeline).
"""
# COMMAND ----------

dbutils.widgets.text("catalog", "", "Catalog")
dbutils.widgets.text("schema", "", "Schema")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG and SCHEMA, "catalog + schema are required"
FQ = f"{CATALOG}.{SCHEMA}"

# COMMAND ----------

ddl = f"""
CREATE OR REPLACE VIEW {FQ}.mv_customer_health
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: {FQ}.gold_daily_health
comment: "Governed customer-health KPI layer (churn risk, on-time delivery, ARR at risk, case load) by date/region/segment. Single source of truth for dashboard tiles and Genie answers."
dimensions:
  - name: date
    expr: date
    comment: "Day"
  - name: region
    expr: region
    comment: "Sales region (NA, EMEA, APAC, LATAM)"
  - name: segment
    expr: segment
    comment: "Customer segment (Enterprise, Mid-Market, SMB)"
measures:
  - name: account_count
    expr: SUM(account_count)
  - name: arr_total
    expr: SUM(arr_total_usd)
  - name: arr_at_risk
    expr: SUM(arr_at_risk_usd)
    comment: "ARR exposed to churn in the affected cohort"
  - name: new_cases
    expr: SUM(new_cases)
  - name: unresolved_cases
    expr: SUM(unresolved_cases)
  - name: shipping_delay_cases
    expr: SUM(shipping_delay_cases)
  - name: orders_count
    expr: SUM(orders_count)
  - name: late_orders
    expr: SUM(late_orders)
  - name: on_time_delivery_rate
    expr: SUM(on_time_orders) / NULLIF(SUM(orders_count), 0)
    comment: "On-time delivery rate; baseline ~0.92, EMEA trough ~0.55 during the slip"
  - name: late_order_rate
    expr: SUM(late_orders) / NULLIF(SUM(orders_count), 0)
  - name: churn_risk_index
    expr: SUM(churn_risk_weighted) / NULLIF(SUM(account_count), 0)
    comment: "Churn-risk index in [1,3]; baseline ~1.0x, EMEA peak ~3x during the slip"
$$
"""

spark.sql(ddl)
print(f"Metric view ready: {FQ}.mv_customer_health")

# COMMAND ----------

# Smoke test — a MEASURE() query must return rows.
df = spark.sql(f"""
  SELECT region,
    ROUND(MEASURE(`churn_risk_index`), 2)      AS churn_risk_index,
    ROUND(MEASURE(`on_time_delivery_rate`), 3) AS on_time_delivery_rate
  FROM {FQ}.mv_customer_health
  WHERE `date` >= date_sub(current_date(), 21)
  GROUP BY region ORDER BY churn_risk_index DESC
""")
df.show()
assert df.count() > 0, "metric view returned no rows"
print("Metric view validated")
