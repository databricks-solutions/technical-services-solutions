from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("job_stage_sales").getOrCreate()

spark.sql("""
CREATE OR REPLACE TABLE stg.sales_clean AS
WITH online AS (
  SELECT sale_id, customer_id, product_id, amount, sale_date FROM raw.sales_online WHERE amount > 0
),
store AS (
  SELECT sale_id, customer_id, product_id, amount, sale_date FROM raw.sales_store WHERE amount > 0
)
SELECT * FROM online
UNION ALL
SELECT * FROM store
""")

spark.sql("""
MERGE INTO stg.customer_latest t
USING raw.customer_updates s
ON t.customer_id = s.customer_id
WHEN MATCHED THEN UPDATE SET t.email = s.email
WHEN NOT MATCHED THEN INSERT *
""")

spark.sql("""
INSERT INTO stg.sales_enriched
SELECT s.sale_id, s.amount, c.region_id, p.category
FROM stg.sales_clean s
JOIN stg.customer_latest c ON s.customer_id = c.customer_id
LEFT JOIN raw.product p ON s.product_id = p.product_id
""")
