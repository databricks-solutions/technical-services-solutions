CREATE TABLE stg.sales_clean WITH (format = 'PARQUET') AS
SELECT s.sale_id, s.amount, c.region FROM raw.sales s JOIN raw.customers c ON s.cust_id = c.cust_id;

INSERT INTO dw.fact_sales SELECT sale_id, COALESCE(amount, 0), region FROM stg.sales_clean;
