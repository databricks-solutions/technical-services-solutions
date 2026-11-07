libname raw "/data/raw";
libname stg "/data/stg";
libname dw "/data/dw";
proc sql;
  create table stg.orders_clean as
  select * from raw.orders where status ne "";
quit;
proc sql;
  create table dw.fact_orders as
  select o.customer_id, count(*) as n
  from stg.orders_clean o inner join raw.customers c on o.customer_id = c.customer_id
  group by o.customer_id;
quit;
