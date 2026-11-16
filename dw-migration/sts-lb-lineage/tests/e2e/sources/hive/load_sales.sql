CREATE TABLE stg.sales_clean STORED AS ORC AS
SELECT s.sale_id, s.amount, c.region FROM raw.sales s JOIN raw.customers c ON s.cust_id = c.cust_id;

INSERT OVERWRITE TABLE dw.fact_sales PARTITION (load_dt='2026-01-01')
SELECT sale_id, NVL(amount, 0), region FROM stg.sales_clean;
