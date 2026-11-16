INSERT OVERWRITE TABLE dw.fact_orders SELECT customer_id, count(*) FROM stg.orders_clean GROUP BY customer_id;
