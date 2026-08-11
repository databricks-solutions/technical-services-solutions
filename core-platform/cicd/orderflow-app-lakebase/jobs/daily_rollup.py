# Databricks notebook source
# Daily business rollup — appends a dated snapshot of key metrics to a gold table
# the business team can trend over time.
from pyspark.sql import functions as F

# COMMAND ----------
dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "orderflow")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

# COMMAND ----------
category_sales = spark.read.table(f"{catalog}.{schema}.gold_category_sales")
status_summary = spark.read.table(f"{catalog}.{schema}.gold_order_status_summary")

total_revenue = category_sales.agg(F.sum("revenue")).collect()[0][0] or 0.0
total_units = category_sales.agg(F.sum("units_sold")).collect()[0][0] or 0
total_orders = status_summary.agg(F.sum("order_count")).collect()[0][0] or 0
open_orders = (
    status_summary.filter(F.col("status").isin("pending", "paid", "shipped"))
    .agg(F.sum("order_count"))
    .collect()[0][0]
    or 0
)

# COMMAND ----------
snapshot = spark.createDataFrame(
    [(float(total_revenue), int(total_units), int(total_orders), int(open_orders))],
    schema="total_revenue double, total_units long, total_orders long, open_orders long",
).withColumn("snapshot_date", F.current_date())

snapshot = snapshot.select(
    "snapshot_date", "total_revenue", "total_units", "total_orders", "open_orders"
)
snapshot.write.mode("append").saveAsTable(f"{catalog}.{schema}.gold_daily_snapshot")

# COMMAND ----------
# Also export the snapshot as a CSV into the UC volume for business consumers.
volume_path = f"/Volumes/{catalog}/{schema}/exports"
dbutils.fs.mkdirs(volume_path)
out = f"{volume_path}/daily_snapshot_{snapshot.first()['snapshot_date']}"
snapshot.coalesce(1).write.mode("overwrite").option("header", "true").csv(out)

print(f"Snapshot: revenue={total_revenue} units={total_units} orders={total_orders} open={open_orders}")
print(f"CSV exported to {out}")
