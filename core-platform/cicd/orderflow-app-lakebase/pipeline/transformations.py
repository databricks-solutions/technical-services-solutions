# OrderFlow medallion transformations (Lakeflow Declarative Pipeline).
#
# Uses the current `pyspark.pipelines` API (the `dlt` module is legacy). Bronze
# tables are landed by the job's `ingest_lakebase` task (raw copies of the
# Lakebase OLTP tables); this pipeline builds silver + gold from them.
#
# All datasets here are batch aggregates, so they are materialized views. Reads
# use spark.read.table (dlt.read is legacy). See:
# https://docs.databricks.com/aws/en/ldp/developer/python-ref
from pyspark import pipelines as dp
from pyspark.sql import functions as F

CATALOG = spark.conf.get("source_catalog")
SCHEMA = spark.conf.get("source_schema")


def _bronze(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.bronze_{name}"


# ---------------------------------------------------------------- SILVER
@dp.materialized_view(comment="Cleaned products with a stock-health flag.")
def silver_products():
    return (
        spark.read.table(_bronze("products"))
        .withColumn("price", F.col("price").cast("decimal(10,2)"))
        .withColumn(
            "stock_status",
            F.when(F.col("stock") <= 0, "out_of_stock")
            .when(F.col("stock") < 100, "low")
            .otherwise("healthy"),
        )
    )


@dp.materialized_view(comment="Order line items enriched with product + order context.")
@dp.expect_or_drop("valid_quantity", "quantity > 0")
def silver_order_items():
    items = spark.read.table(_bronze("order_items"))
    orders = spark.read.table(_bronze("orders")).select(
        F.col("id").alias("order_id"),
        F.col("customer_id"),
        F.col("status").alias("order_status"),
        F.col("created_at").alias("order_created_at"),
    )
    products = spark.read.table(_bronze("products")).select(
        F.col("id").alias("product_id"),
        F.col("name").alias("product_name"),
        F.col("category"),
    )
    return (
        items.join(orders, "order_id")
        .join(products, "product_id")
        .withColumn("line_total", F.col("quantity") * F.col("unit_price"))
    )


# ---------------------------------------------------------------- GOLD
@dp.materialized_view(comment="Revenue and units sold per product category.")
def gold_category_sales():
    return (
        spark.read.table("silver_order_items")
        .groupBy("category")
        .agg(
            F.round(F.sum("line_total"), 2).alias("revenue"),
            F.sum("quantity").alias("units_sold"),
            F.countDistinct("order_id").alias("orders"),
        )
        .orderBy(F.desc("revenue"))
    )


@dp.materialized_view(comment="Order funnel: count and value by order status.")
def gold_order_status_summary():
    orders = spark.read.table(_bronze("orders"))
    return (
        orders.groupBy("status")
        .agg(
            F.count("*").alias("order_count"),
            F.round(F.sum("total"), 2).alias("total_value"),
        )
        .orderBy(F.desc("order_count"))
    )


@dp.materialized_view(comment="Inventory watchlist — products needing a restock.")
def gold_low_stock():
    return (
        spark.read.table("silver_products")
        .filter(F.col("stock_status") != "healthy")
        .select("sku", "name", "category", "stock", "stock_status")
        .orderBy("stock")
    )
