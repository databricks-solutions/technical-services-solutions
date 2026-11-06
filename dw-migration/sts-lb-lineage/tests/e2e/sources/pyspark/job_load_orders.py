from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("job_load_orders").getOrCreate()
spark.sql(
    "INSERT INTO stg.orders_clean SELECT * FROM raw.orders WHERE status IS NOT NULL"
)
spark.sql("""
INSERT INTO dw.fact_orders
SELECT o.customer_id, count(*) AS n
FROM stg.orders_clean o JOIN raw.customers c ON o.customer_id = c.customer_id
GROUP BY o.customer_id
""")
spark.sql(
    "CREATE TABLE dw.fact_orders_daily AS SELECT order_date, count(*) AS n FROM dw.fact_orders GROUP BY order_date"
)
