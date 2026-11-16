CREATE TABLE stg.sales_clean AS
SELECT s.sale_id, s.amount, c.region FROM raw.sales s JOIN raw.customers c ON s.cust_id = c.cust_id
SEGMENTED BY HASH(sale_id) ALL NODES;

INSERT INTO dw.fact_sales (sale_id, amount, region)
SELECT sale_id, NVL(amount, 0), region FROM stg.sales_clean;
