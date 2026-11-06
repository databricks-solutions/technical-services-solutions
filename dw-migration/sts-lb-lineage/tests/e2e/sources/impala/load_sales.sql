CREATE TABLE stg.sales_clean STORED AS PARQUET AS
SELECT s.sale_id, s.amount, c.region FROM raw.sales s JOIN raw.customers c ON s.cust_id = c.cust_id;

INSERT OVERWRITE TABLE dw.fact_sales SELECT sale_id, NVL(amount, 0), region FROM stg.sales_clean;
