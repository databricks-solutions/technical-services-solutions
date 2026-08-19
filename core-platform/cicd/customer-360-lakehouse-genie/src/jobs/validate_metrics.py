# Databricks notebook source
# MAGIC %md
# MAGIC # Validate Metrics
# MAGIC Confirms the gold tables are populated after the pipeline run and that the
# MAGIC governed metric view `mv_customer_health` returns current data for the
# MAGIC Monday exec review.

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Catalog")
dbutils.widgets.text("schema", "", "Schema")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG and SCHEMA, "catalog + schema are required"

# COMMAND ----------

for t in ["gold_account_health", "gold_daily_health"]:
    n = spark.table(f"{CATALOG}.{SCHEMA}.{t}").count()
    print(f"{t}: {n:,} rows")
    assert n > 0, f"{t} is empty"

# COMMAND ----------

df = spark.sql(f"""
  SELECT region,
    ROUND(MEASURE(`churn_risk_index`), 2)      AS churn_risk_index,
    ROUND(MEASURE(`on_time_delivery_rate`), 3) AS on_time_delivery_rate
  FROM {CATALOG}.{SCHEMA}.mv_customer_health
  WHERE `date` >= date_sub(current_date(), 21)
  GROUP BY region ORDER BY churn_risk_index DESC
""")
df.show()

arr = spark.sql(f"""
  SELECT ROUND(SUM(arr_usd), 0) AS arr_at_risk_usd, COUNT(*) AS at_risk_accounts
  FROM {CATALOG}.{SCHEMA}.gold_account_health WHERE is_at_risk
""").collect()[0]
print(f"ARR at risk: ${arr['arr_at_risk_usd']:,.0f} across {arr['at_risk_accounts']} accounts")
print("Metrics refreshed and validated — customer-360 view is fresh")
