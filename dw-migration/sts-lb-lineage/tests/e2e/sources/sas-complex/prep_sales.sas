%let yr = 2025;
libname raw "/data/raw";
libname stg "/data/stg";
libname work "/tmp/work";

proc sql;
  create table work.sales_yr as
  select s.sale_id, s.customer_id, s.amount
  from raw.sales s
  inner join raw.customer c on s.customer_id = c.customer_id
  where year(s.sale_date) = &yr;
quit;

proc sql;
  create table stg.sales_clean as
  select w.sale_id, w.amount, r.region_name
  from work.sales_yr w
  left join raw.region r on w.customer_id = r.customer_id
  where w.amount > (select avg(amount) from work.sales_yr);
quit;

proc sql;
  insert into stg.sales_clean
  select sale_id, amount, region_name from raw.sales_archive;
quit;
