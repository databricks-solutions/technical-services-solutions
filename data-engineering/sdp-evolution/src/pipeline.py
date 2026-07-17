# SDP (Spark Declarative Pipelines) - schema evolution demo.
#
# Bronze ingests JSON with Auto Loader in "rescue" schema-evolution mode: any
# column that gets renamed, retyped, or newly added after v1 is captured in the
# _rescued_data column instead of failing the stream. That means the pipeline
# keeps running through drift, and all the drifted data is recoverable later.

from pyspark import pipelines as dp
from pyspark.sql import functions as F

# Bundle deploys src/ onto the path, so this sibling import resolves.
from reconcile import reconcile, RESCUE_SCHEMA  # noqa: F401

source_path = spark.conf.get("source.path")

BRONZE_SCHEMA = "order_id string, cust_name string, amount string, order_ts string"


@dp.table(name="orders_bronze")
def orders_bronze():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.schemaEvolutionMode", "rescue")
        .option("rescuedDataColumn", "_rescued_data")
        .schema(BRONZE_SCHEMA)
        .load(source_path)
    )


@dp.materialized_view(name="orders_silver")
def orders_silver():
    df = spark.read.table("orders_bronze")
    # ==== STEP 4: SCHEMA EVOLUTION RECONCILIATION ====
    # Two states of this view:
    #
    #   STATE 1 (shipped, active below): silver simply passes through the fixed
    #   v1 business columns. After v2 drift, new rows show null customer_name /
    #   amount because the upstream renamed/retyped fields were rescued into
    #   _rescued_data rather than the base columns.
    #
    #   STATE 2 (the fix): wrap the STATE 1 passthrough return in triple quotes
    #   and activate `return reconcile(df)`. reconcile() coalesces each business
    #   column with the matching field pulled back out of _rescued_data, so both
    #   old v1 rows and new v2 rows resolve correctly.
    
    # START OF STATE 1
    return df.select(
        "order_id",
        F.col("cust_name").alias("customer_name"),
        F.col("amount").cast("double").alias("amount"),
        F.lit(None).cast("string").alias("loyalty_tier"),
        "order_ts",
    )
    # END OF STATE 1

    # START OF STATE 2
    # return reconcile(df)
    # END OF STATE 2
