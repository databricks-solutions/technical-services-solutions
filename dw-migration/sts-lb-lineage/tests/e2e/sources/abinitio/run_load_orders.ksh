#!/bin/ksh
# job_load_orders wrapper
. $AB_HOME/bin/ab_env.ksh
m_db unload dwh.dbc -table raw.orders > /data/raw_orders.dat
./load_orders.ksh
m_db load dwh.dbc -table dw.fact_orders -file /data/stg_orders_clean.dat
echo "INSERT INTO dw.fact_orders SELECT order_id, amount FROM stg.orders_clean" | sqlplus -s user/pwd@db
