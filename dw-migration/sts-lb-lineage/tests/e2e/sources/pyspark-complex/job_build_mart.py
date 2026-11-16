from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("job_build_mart").getOrCreate()

spark.sql(
    "SELECT * FROM stg.sales_enriched WHERE amount > 100"
).createOrReplaceTempView("big_sales")

spark.sql("""
INSERT INTO dw.fact_sales
SELECT b.sale_id, b.amount, r.region_name
FROM big_sales b
JOIN raw.region r ON b.region_id = r.region_id
""")

spark.sql("""
INSERT INTO mart.sales_by_region
SELECT region_name, sum(amount) AS total
FROM dw.fact_sales
GROUP BY region_name
UNION ALL
SELECT 'ALL' AS region_name, sum(amount) FROM dw.fact_sales
""")
