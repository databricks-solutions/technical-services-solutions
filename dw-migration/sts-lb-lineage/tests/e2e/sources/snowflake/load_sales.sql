CREATE OR REPLACE TRANSIENT TABLE stg.sales_clean AS
SELECT s.sale_id, s.amount, c.region FROM raw.sales s JOIN raw.customers c ON s.cust_id = c.cust_id;

INSERT INTO dw.fact_sales (sale_id, amount, region)
SELECT sale_id, IFF(amount IS NULL, 0, amount), region FROM stg.sales_clean;
