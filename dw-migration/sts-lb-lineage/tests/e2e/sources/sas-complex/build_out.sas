%let mon = 202511;
libname stg "/data/stg";
libname out "/data/out";
libname work "/tmp/work";

proc sql;
  create table work.top_regions as
  select region_name, sum(amount) as total
  from stg.sales_clean
  group by region_name;
quit;

proc sql;
  create table out.region_summary as
  select t.region_name, t.total, t.total / d.grand as share
  from work.top_regions t, (select sum(total) as grand from work.top_regions) d;
quit;

proc sql;
  insert into out.region_history
  select r.region_name, r.total, p.target
  from out.region_summary r
  join stg.region_targets p on r.region_name = p.region_name;
quit;
