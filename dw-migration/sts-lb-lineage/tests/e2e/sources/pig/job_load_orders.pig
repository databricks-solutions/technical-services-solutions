raw_orders = LOAD 'raw.orders' USING org.apache.hive.hcatalog.pig.HCatLoader();
clean = FILTER raw_orders BY status IS NOT NULL;
STORE clean INTO 'stg.orders_clean' USING org.apache.hive.hcatalog.pig.HCatStorer();
stg = LOAD 'stg.orders_clean' USING org.apache.hive.hcatalog.pig.HCatLoader();
grp = GROUP stg BY customer_id;
fact = FOREACH grp GENERATE group AS customer_id, COUNT(stg) AS n;
STORE fact INTO 'dw.fact_orders' USING org.apache.hive.hcatalog.pig.HCatStorer();
