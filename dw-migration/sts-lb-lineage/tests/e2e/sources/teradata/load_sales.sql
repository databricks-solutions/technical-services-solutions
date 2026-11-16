CREATE TABLE stg.sales_clean AS (
SEL s.sale_id, s.amount, c.region FROM raw.sales s JOIN raw.customers c ON s.cust_id = c.cust_id
) WITH DATA PRIMARY INDEX (sale_id);

INS INTO dw.fact_sales (sale_id, amount, region)
SEL sale_id, ZEROIFNULL(amount), region FROM stg.sales_clean;
