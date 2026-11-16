INSERT OVERWRITE TABLE stg.orders_clean SELECT * FROM raw.orders WHERE status IS NOT NULL;
