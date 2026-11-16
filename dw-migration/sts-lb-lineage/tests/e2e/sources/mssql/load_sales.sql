SELECT s.sale_id, s.amount, c.region
INTO stg.sales_clean
FROM raw.sales s JOIN raw.customers c ON s.cust_id = c.cust_id;
GO

INSERT INTO dw.fact_sales (sale_id, amount, region)
SELECT sale_id, ISNULL(amount, 0), region FROM stg.sales_clean;
GO
