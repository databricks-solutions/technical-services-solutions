# Databricks notebook source
# Ingest the OrderFlow Lakebase OLTP tables into UC bronze tables.
#
# Uses a short-lived OAuth credential minted from the workspace identity, so no
# passwords are stored. Runs on serverless compute with psycopg installed via
# the job's environment spec.
import psycopg
from databricks.sdk import WorkspaceClient
from pyspark.sql import functions as F

# COMMAND ----------
dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "orderflow")
dbutils.widgets.text("lakebase_endpoint", "projects/orderflow-db/branches/production/endpoints/primary")
dbutils.widgets.text("lakebase_host", "")
dbutils.widgets.text("lakebase_database", "orderflow")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
endpoint = dbutils.widgets.get("lakebase_endpoint")
host = dbutils.widgets.get("lakebase_host")
database = dbutils.widgets.get("lakebase_database")

# COMMAND ----------
w = WorkspaceClient()
token = w.postgres.generate_database_credential(endpoint=endpoint).token
user = w.current_user.me().user_name

conninfo = f"host={host} port=5432 dbname={database} user={user} password={token} sslmode=require"

TABLES = ["products", "customers", "orders", "order_items"]

# COMMAND ----------
# Read each Postgres table and write a bronze Delta copy.
with psycopg.connect(conninfo) as conn:
    for table in TABLES:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table}")
            cols = [d.name for d in cur.description]
            rows = cur.fetchall()
        # Cast everything to string-friendly Python types Spark can infer.
        data = [dict(zip(cols, [str(v) if v is not None else None for v in row])) for row in rows]
        target = f"{catalog}.{schema}.bronze_{table}"
        if data:
            sdf = spark.createDataFrame(data)
        else:
            sdf = spark.createDataFrame([], schema="id string")
        sdf = sdf.withColumn("_ingested_at", F.current_timestamp())
        sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)
        print(f"wrote {sdf.count()} rows -> {target}")

# COMMAND ----------
print("Bronze ingest complete.")
