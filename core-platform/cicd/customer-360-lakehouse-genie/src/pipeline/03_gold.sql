-- ---------- GOLD ----------
-- Per-account current-snapshot health
CREATE OR REFRESH MATERIALIZED VIEW gold_account_health
COMMENT "One row per account: 30-day health + churn risk + at-risk flag"
AS
WITH orders30 AS (
  SELECT account_id,
         COUNT(*) AS orders_30d,
         SUM(CASE WHEN is_late THEN 1 ELSE 0 END) AS late_orders_30d
  FROM silver_orders
  WHERE order_date >= DATE_SUB(current_date(), 30)
  GROUP BY account_id
),
cases_open AS (
  SELECT account_id, COUNT(*) AS open_cases_30d
  FROM silver_cases
  WHERE is_unresolved
  GROUP BY account_id
),
base AS (
  SELECT a.*,
         COALESCE(o.orders_30d, 0) AS orders_30d,
         COALESCE(o.late_orders_30d, 0) AS late_orders_30d,
         COALESCE( c.open_cases_30d, 0) AS open_cases_30d
  FROM silver_accounts a
  LEFT JOIN orders30 o USING (account_id)
  LEFT JOIN cases_open c USING (account_id)
)
SELECT
  account_id, account_name, region, country, segment, industry, arr_usd,
  renewal_date, days_to_renewal, renewal_window,
  orders_30d, late_orders_30d, open_cases_30d,
  ROUND(1.0 - late_orders_30d / NULLIF(orders_30d, 0), 3) AS on_time_rate_30d,
  -- churn components
  LEAST(1.0, GREATEST(0.0, (late_orders_30d / NULLIF(orders_30d, 0) - 0.08) / (0.45 - 0.08))) AS c_delivery,
  LEAST(1.0, open_cases_30d / 5.0) AS c_cases,
  CASE WHEN days_to_renewal <= 90 THEN 1.0 WHEN days_to_renewal <= 180 THEN 0.5 ELSE 0.2 END AS c_renewal,
  ROUND(100 * (0.5 * LEAST(1.0, GREATEST(0.0, (late_orders_30d / NULLIF(orders_30d, 0) - 0.08) / (0.45 - 0.08)))
             + 0.3 * LEAST(1.0, open_cases_30d / 5.0)
             + 0.2 * (CASE WHEN days_to_renewal <= 90 THEN 1.0 WHEN days_to_renewal <= 180 THEN 0.5 ELSE 0.2 END))) AS churn_risk_score,
  ROUND(1 + 2 * (0.5 * LEAST(1.0, GREATEST(0.0, (late_orders_30d / NULLIF(orders_30d, 0) - 0.08) / (0.45 - 0.08)))
             + 0.3 * LEAST(1.0, open_cases_30d / 5.0)
             + 0.2 * (CASE WHEN days_to_renewal <= 90 THEN 1.0 WHEN days_to_renewal <= 180 THEN 0.5 ELSE 0.2 END)), 2) AS churn_risk_index,
  is_cohort AS is_at_risk,
  CASE WHEN is_cohort THEN arr_usd ELSE 0 END AS arr_at_risk_usd
FROM base;

-- Daily time-series by region x segment (metric-view source)
CREATE OR REFRESH MATERIALIZED VIEW gold_daily_health
COMMENT "Daily region x segment health metrics: churn index, delivery, case backlog, ARR at risk"
AS
WITH spine AS (
  SELECT explode(sequence(DATE_SUB(current_date(), 548), current_date(), interval 1 day)) AS date
),
slices AS (
  SELECT region, segment,
         COUNT(*) AS account_count,
         SUM(arr_usd) AS arr_total_usd,
         SUM(CASE WHEN is_cohort THEN arr_usd ELSE 0 END) AS cohort_arr
  FROM silver_accounts
  GROUP BY region, segment
),
orders_daily AS (
  SELECT order_date AS date, region, segment,
         COUNT(*) AS orders_count,
         SUM(CASE WHEN is_late THEN 1 ELSE 0 END) AS late_orders,
         SUM(CASE WHEN NOT is_late THEN 1 ELSE 0 END) AS on_time_orders
  FROM silver_orders GROUP BY order_date, region, segment
),
new_cases_daily AS (
  SELECT opened_date AS date, region, segment, COUNT(*) AS new_cases
  FROM silver_cases GROUP BY opened_date, region, segment
),
case_days AS (
  SELECT explode(sequence(opened_date, COALESCE(resolved_date, current_date()), interval 1 day)) AS date,
         region, segment, category
  FROM silver_cases
),
backlog_daily AS (
  SELECT date, region, segment,
         COUNT(*) AS unresolved_cases,
         SUM(CASE WHEN category = 'shipping_delay' THEN 1 ELSE 0 END) AS shipping_delay_cases
  FROM case_days GROUP BY date, region, segment
),
joined AS (
  SELECT sp.date, sl.region, sl.segment, sl.account_count, sl.arr_total_usd, sl.cohort_arr,
         COALESCE(o.orders_count, 0) AS orders_count,
         COALESCE(o.late_orders, 0) AS late_orders,
         COALESCE(o.on_time_orders, 0) AS on_time_orders,
         COALESCE(nc.new_cases, 0) AS new_cases,
         COALESCE(b.unresolved_cases, 0) AS unresolved_cases,
         COALESCE(b.shipping_delay_cases, 0) AS shipping_delay_cases
  FROM spine sp
  CROSS JOIN slices sl
  LEFT JOIN orders_daily o ON o.date = sp.date AND o.region = sl.region AND o.segment = sl.segment
  LEFT JOIN new_cases_daily nc ON nc.date = sp.date AND nc.region = sl.region AND nc.segment = sl.segment
  LEFT JOIN backlog_daily b ON b.date = sp.date AND b.region = sl.region AND b.segment = sl.segment
)
SELECT
  date, region, segment, account_count, arr_total_usd,
  new_cases, unresolved_cases, shipping_delay_cases,
  orders_count, late_orders, on_time_orders,
  -- delivery stress -> churn index in [1,3]
  ROUND((1 + 2 * LEAST(1.0, GREATEST(0.0,
        (late_orders / NULLIF(orders_count, 0) - 0.08) / (0.45 - 0.08)))) * account_count, 3) AS churn_risk_weighted,
  ROUND(cohort_arr * LEAST(1.0, GREATEST(0.0,
        (late_orders / NULLIF(orders_count, 0) - 0.08) / (0.45 - 0.08))), 0) AS arr_at_risk_usd
FROM joined;
