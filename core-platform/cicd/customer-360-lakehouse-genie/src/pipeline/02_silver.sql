-- ---------- SILVER (cleaned + enriched) ----------
CREATE OR REFRESH MATERIALIZED VIEW silver_accounts
COMMENT "Cleaned account dimension with renewal proximity"
AS SELECT
  account_id, account_name, region, country, segment, industry,
  arr_usd, contract_start_date, renewal_date, csm_owner, employees, signup_date,
  is_cohort,
  DATEDIFF(renewal_date, current_date()) AS days_to_renewal,
  CASE WHEN DATEDIFF(renewal_date, current_date()) <= 90 THEN '<=90d'
       WHEN DATEDIFF(renewal_date, current_date()) <= 180 THEN '<=180d'
       ELSE '>180d' END AS renewal_window
FROM bronze_accounts;

CREATE OR REFRESH MATERIALIZED VIEW silver_orders
COMMENT "Order fact with lateness flags, enriched with account segment"
AS SELECT
  o.order_id, o.account_id, o.region, a.segment, a.industry,
  o.order_date, o.promised_ship_date, o.actual_ship_date,
  o.amount_usd, o.status, o.carrier,
  (o.actual_ship_date > o.promised_ship_date) AS is_late,
  DATEDIFF(o.actual_ship_date, o.promised_ship_date) AS ship_delay_days
FROM bronze_orders o
JOIN silver_accounts a USING (account_id);

CREATE OR REFRESH MATERIALIZED VIEW silver_cases
COMMENT "Case fact with resolution + backlog flags, enriched with account segment"
AS SELECT
  c.case_id, c.account_id, c.region, a.segment,
  c.opened_at, c.resolved_at,
  CAST(c.opened_at AS DATE) AS opened_date,
  CAST(c.resolved_at AS DATE) AS resolved_date,
  c.status, c.priority, c.category, c.subject, c.csat,
  (c.status IN ('open','pending')) AS is_unresolved,
  DATEDIFF(CAST(c.resolved_at AS DATE), CAST(c.opened_at AS DATE)) AS resolution_days
FROM bronze_cases c
JOIN silver_accounts a USING (account_id);
