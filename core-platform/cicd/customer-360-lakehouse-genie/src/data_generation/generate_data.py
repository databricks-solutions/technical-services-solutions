# Databricks notebook source
"""
Vela Cloud — Customer 360 Lakehouse
Synthetic data generation → parquet on UC Volume (raw landing zone for SDP).

Story: an EMEA fulfillment slip (~5 weeks ago) blew out shipping times; late orders
drove a support-case surge; churn risk hit ~3x on the largest EMEA renewals; a $1.4M
renewal is exposed. Peak ~3 weeks ago, decaying but still elevated.

Datasets written to /Volumes/{CATALOG}/{SCHEMA}/raw_data/{accounts,orders,cases}

Runs as a bundle setup-job notebook task (serverless `spark` already available).
catalog/schema come from base_parameters so every task uses the same values.
"""
# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.window import Window
from datetime import datetime
import numpy as np

dbutils.widgets.text("catalog", "", "Catalog")
dbutils.widgets.text("schema", "", "Schema")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG and SCHEMA, "catalog + schema are required"
VOL = f"/Volumes/{CATALOG}/{SCHEMA}/raw_data"

# ---- Time anchors (rolling off today) ----
NOW = datetime.now().date()
DAYS_HISTORY = 548  # ~18 months
SLIP_START_AGO = 35   # EMEA slip begins
SPIKE_PEAK_AGO = 21   # peak churn / worst on-time / case backlog peak
DECAY_START_AGO = 14

SEED = 42

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.raw_data")

# COMMAND ----------

# =====================================================================
# ACCOUNTS (30,000)
# =====================================================================
N_ACCOUNTS = 30000

_COMP_A = ["Apex", "Blue", "North", "Summit", "Vertex", "Cedar", "Quantum", "Orbit",
           "Pioneer", "Nova", "Atlas", "Delta", "Harbor", "Iron", "Silver", "Global"]
_COMP_B = ["Systems", "Logic", "Dynamics", "Works", "Labs", "Networks", "Digital",
           "Solutions", "Group", "Analytics", "Cloud", "Data", "Partners", "Industries"]
_COMP_C = ["Inc", "LLC", "GmbH", "Ltd", "Co", "SA", "AG", "BV"]
_FIRST = ["Maya", "Liam", "Sofia", "Noah", "Emma", "Lucas", "Olivia", "Ethan",
          "Ava", "Marco", "Chen", "Priya", "Yuki", "Hans", "Elena", "Diego"]
_LAST = ["Patel", "Smith", "Garcia", "Muller", "Rossi", "Kim", "Nguyen", "Dubois",
         "Silva", "Cohen", "Tanaka", "Novak", "Andersen", "Costa", "Fischer", "Weber"]

def _pick(arr, salt):
    return F.element_at(F.array(*[F.lit(x) for x in arr]),
                        (F.abs(F.hash(F.col("id") + F.lit(salt))) % len(arr) + 1).cast("int"))

acc = spark.range(0, N_ACCOUNTS, numPartitions=16).withColumn("r", F.rand(SEED))
# region
acc = acc.withColumn("region",
    F.when(F.col("r") < 0.40, F.lit("NA"))
     .when(F.col("r") < 0.70, F.lit("EMEA"))
     .when(F.col("r") < 0.90, F.lit("APAC"))
     .otherwise(F.lit("LATAM")))
# segment (independent draw)
acc = acc.withColumn("rs", F.rand(SEED + 1)).withColumn("segment",
    F.when(F.col("rs") < 0.10, F.lit("Enterprise"))
     .when(F.col("rs") < 0.40, F.lit("Mid-Market"))
     .otherwise(F.lit("SMB")))
# ARR by segment (lognormal-ish via rand bands)
acc = acc.withColumn("ra", F.rand(SEED + 2)).withColumn("arr_usd",
    F.when(F.col("segment") == "Enterprise", F.round(80000 + F.col("ra") * 320000, 0))
     .when(F.col("segment") == "Mid-Market", F.round(15000 + F.col("ra") * 65000, 0))
     .otherwise(F.round(2000 + F.col("ra") * 13000, 0)))
# country within region
acc = acc.withColumn("rc", F.rand(SEED + 3))
acc = acc.withColumn("country",
    F.when(F.col("region") == "EMEA",
        F.when(F.col("rc") < 0.25, "DE").when(F.col("rc") < 0.47, "GB")
         .when(F.col("rc") < 0.67, "FR").when(F.col("rc") < 0.79, "NL")
         .when(F.col("rc") < 0.90, "IT").otherwise("ES"))
     .when(F.col("region") == "NA",
        F.when(F.col("rc") < 0.85, "US").otherwise("CA"))
     .when(F.col("region") == "APAC",
        F.when(F.col("rc") < 0.40, "JP").when(F.col("rc") < 0.70, "AU")
         .when(F.col("rc") < 0.88, "SG").otherwise("IN"))
     .otherwise(
        F.when(F.col("rc") < 0.55, "BR").when(F.col("rc") < 0.80, "MX").otherwise("AR")))
industries = ["Financial Services", "Healthcare", "Retail", "Manufacturing",
              "Technology", "Media", "Logistics", "Energy"]
acc = acc.withColumn("industry",
    F.element_at(F.array(*[F.lit(x) for x in industries]),
                 (F.col("id") % len(industries) + 1).cast("int")))
acc = acc.withColumn("employees",
    F.when(F.col("segment") == "Enterprise", (F.rand(SEED+4)*9000 + 1000).cast("int"))
     .when(F.col("segment") == "Mid-Market", (F.rand(SEED+4)*900 + 100).cast("int"))
     .otherwise((F.rand(SEED+4)*90 + 10).cast("int")))
# renewal_date: uniform in next 365 days
acc = acc.withColumn("renewal_offset", (F.rand(SEED+5) * 365 + 1).cast("int"))
acc = acc.withColumn("renewal_date", F.date_add(F.lit(NOW.isoformat()).cast("date"), F.col("renewal_offset")))
acc = acc.withColumn("contract_start_date", F.date_sub(F.col("renewal_date"), 365))
acc = acc.withColumn("signup_date", F.date_sub(F.col("contract_start_date"),
                                               (F.rand(SEED+6)*720).cast("int")))
acc = acc.withColumn("account_id", F.concat(F.lit("ACC-"), F.lpad(F.col("id").cast("string"), 6, "0")))
acc = acc.withColumn("account_name",
    F.concat_ws(" ", _pick(_COMP_A, 100), _pick(_COMP_B, 200), _pick(_COMP_C, 300)))
acc = acc.withColumn("csm_owner",
    F.concat_ws(" ", _pick(_FIRST, 400), _pick(_LAST, 500)))

# ---- At-risk cohort: ~14 EMEA Enterprise accounts, renewal in 30-90 days, ARR ~100K each -> sum ~1.4M ----
emea_ent = acc.filter((F.col("region") == "EMEA") & (F.col("segment") == "Enterprise"))
w = Window.orderBy(F.col("id"))
emea_ent_ranked = emea_ent.withColumn("rk", F.row_number().over(w))
cohort_ids = [row["id"] for row in emea_ent_ranked.filter(F.col("rk") <= 14).select("id").collect()]
# assign target ARRs summing to ~1,400,000
rng = np.random.default_rng(SEED)
target = np.round(rng.uniform(90000, 180000, size=len(cohort_ids)))
target = np.round(target * (1400000.0 / target.sum()) / 1000.0) * 1000.0  # scale to sum ~1.4M, round to 1k
cohort_map = {int(i): float(a) for i, a in zip(cohort_ids, target)}
print(f"Cohort accounts: {len(cohort_ids)}, ARR sum = {target.sum():,.0f}")

# apply via when-chain (small list)
arr_expr = F.col("arr_usd")
renew_expr = F.col("renewal_offset")
for cid, carr in cohort_map.items():
    arr_expr = F.when(F.col("id") == cid, F.lit(carr)).otherwise(arr_expr)
# renewal 30-90 days for cohort (deterministic spread)
for k, cid in enumerate(cohort_ids):
    renew_expr = F.when(F.col("id") == cid, F.lit(30 + (k * 4) % 60)).otherwise(renew_expr)
acc = acc.withColumn("arr_usd", arr_expr).withColumn("renewal_offset", renew_expr)
acc = acc.withColumn("renewal_date", F.date_add(F.lit(NOW.isoformat()).cast("date"), F.col("renewal_offset")))
acc = acc.withColumn("is_cohort", F.col("id").isin(cohort_ids))

accounts = acc.select(
    "account_id", "account_name", "region", "country", "segment", "industry",
    F.col("arr_usd").cast("double").alias("arr_usd"),
    "contract_start_date", "renewal_date", "csm_owner", "employees", "signup_date",
    "is_cohort")

# inject ~0.5% dirty rows (bad region / null arr) for expectations to drop
dirty = accounts.sample(0.005, seed=SEED).withColumn("region", F.lit("ZZ")) \
    .withColumn("arr_usd", F.lit(-1.0))
accounts_out = accounts.unionByName(dirty)
accounts_out.write.mode("overwrite").parquet(f"{VOL}/accounts")
print("accounts written:", accounts_out.count())

# save clean accounts as delta for FK lookups
accounts.write.mode("overwrite").saveAsTable(f"{CATALOG}.{SCHEMA}._gen_accounts")
acc_lu = spark.table(f"{CATALOG}.{SCHEMA}._gen_accounts").select("account_id", "region", "segment", "is_cohort")

# COMMAND ----------

# =====================================================================
# ORDERS (~550K)
# =====================================================================
N_ORDERS = 550000
# assign orders to accounts by hash; join region
orders = spark.range(0, N_ORDERS, numPartitions=32)
orders = orders.withColumn("acc_idx", (F.abs(F.hash(F.col("id"))) % N_ACCOUNTS))
orders = orders.withColumn("account_id", F.concat(F.lit("ACC-"), F.lpad(F.col("acc_idx").cast("string"), 6, "0")))
orders = orders.join(acc_lu, "account_id", "left")
# order_date uniform over history
orders = orders.withColumn("days_back", (F.rand(SEED+10) * DAYS_HISTORY).cast("int"))
orders = orders.withColumn("order_date", F.date_sub(F.lit(NOW.isoformat()).cast("date"), F.col("days_back")))
orders = orders.withColumn("days_ago", F.datediff(F.lit(NOW.isoformat()).cast("date"), F.col("order_date")))
orders = orders.withColumn("promised_ship_date", F.date_add(F.col("order_date"), 3))
# EMEA late-rate ramp
emea = (F.col("region") == "EMEA")
da = F.col("days_ago")
late_rate = (
    F.when(~emea, F.lit(0.08))
     .when((da >= 21) & (da <= 35), 0.08 + (35 - da) / 14.0 * (0.45 - 0.08))
     .when((da >= 0) & (da < 21), 0.20 + da / 21.0 * (0.45 - 0.20))
     .otherwise(F.lit(0.08)))
orders = orders.withColumn("late_rate", late_rate)
orders = orders.withColumn("is_late_draw", F.rand(SEED+11) < F.col("late_rate"))
orders = orders.withColumn("delay_days",
    F.when(F.col("is_late_draw"), (F.rand(SEED+12) * 8 + 4).cast("int"))
     .otherwise((F.rand(SEED+12) * 2 - 1).cast("int")))  # -1..0
orders = orders.withColumn("actual_ship_date", F.date_add(F.col("promised_ship_date"), F.col("delay_days")))
orders = orders.withColumn("amount_usd", F.round(F.rand(SEED+13) * 4800 + 200, 2))
carriers = ["DHL", "FedEx", "UPS", "TNT", "Local"]
orders = orders.withColumn("carrier",
    F.element_at(F.array(*[F.lit(x) for x in carriers]), (F.abs(F.hash(F.col("id"))) % 5 + 1).cast("int")))
orders = orders.withColumn("status",
    F.when(F.col("days_ago") < 2, F.lit("in_transit")).otherwise(F.lit("delivered")))
orders = orders.withColumn("order_id",
    F.concat(F.lit("ORD-"), F.date_format(F.col("order_date"), "yyyyMMdd"), F.lit("-"),
             F.lpad(F.col("id").cast("string"), 6, "0")))
orders_out = orders.select("order_id", "account_id", "region", "order_date",
    "promised_ship_date", "actual_ship_date",
    F.col("amount_usd").cast("double").alias("amount_usd"), "status", "carrier")
# dirty rows: null account, negative amount
odirty = orders_out.sample(0.004, seed=SEED).withColumn("account_id", F.lit(None).cast("string"))
orders_out2 = orders_out.unionByName(odirty)
orders_out2.write.mode("overwrite").parquet(f"{VOL}/orders")
print("orders written:", orders_out2.count())

# COMMAND ----------

# =====================================================================
# CASES  (baseline ~200K + EMEA event ~28K)
# =====================================================================
def build_cases(df, event=False):
    df = df.join(acc_lu, "account_id", "left")
    if not event:
        df = df.withColumn("days_back", (F.rand(SEED+20) * DAYS_HISTORY).cast("int"))
        df = df.withColumn("opened_date", F.date_sub(F.lit(NOW.isoformat()).cast("date"), F.col("days_back")))
        rcat = F.rand(SEED+21)
        df = df.withColumn("category",
            F.when(rcat < 0.38, "how_to").when(rcat < 0.60, "billing")
             .when(rcat < 0.78, "product_bug").when(rcat < 0.90, "feature_request")
             .otherwise("shipping_delay"))
        # baseline: essentially all resolved (short intervals)
        df = df.withColumn("res_delay",
            F.when(F.rand(SEED+22) < 0.85, (F.rand(SEED+23) * 5 + 1).cast("int"))
             .otherwise((F.rand(SEED+23) * 13 + 7).cast("int")))
        df = df.withColumn("resolved_date", F.date_add(F.col("opened_date"), F.col("res_delay")))
        # if resolved in future (recent case), keep open
        df = df.withColumn("resolved_date",
            F.when(F.col("resolved_date") > F.lit(NOW.isoformat()).cast("date"), F.lit(None).cast("date"))
             .otherwise(F.col("resolved_date")))
        df = df.withColumn("priority",
            F.when(F.rand(SEED+24) < 0.15, "P1").when(F.rand(SEED+24) < 0.5, "P2").otherwise("P3"))
        df = df.withColumn("csat",
            F.when(F.col("resolved_date").isNotNull(), (F.rand(SEED+25) * 2 + 3).cast("int"))
             .otherwise(F.lit(None).cast("int")))
        df = df.withColumn("subject", F.concat(F.lit("Case: "), F.col("category")))
    else:
        # EMEA event: shipping_delay, opened in slip window (days_ago 14-35, peak ~21), mostly unresolved
        df = df.filter(F.col("region") == "EMEA")
        # concentrate opened around peak: triangular-ish via two rands
        df = df.withColumn("da", (14 + F.rand(SEED+30) * 21).cast("int"))  # 14..35
        df = df.withColumn("opened_date", F.date_sub(F.lit(NOW.isoformat()).cast("date"), F.col("da")))
        df = df.withColumn("category", F.lit("shipping_delay"))
        # 40% resolved recently (recovery), 60% still open
        df = df.withColumn("resolved_date",
            F.when(F.rand(SEED+31) < 0.40,
                   F.date_sub(F.lit(NOW.isoformat()).cast("date"), (F.rand(SEED+32) * 10).cast("int")))
             .otherwise(F.lit(None).cast("date")))
        df = df.withColumn("priority", F.when(F.rand(SEED+33) < 0.5, "P1").otherwise("P2"))
        df = df.withColumn("csat",
            F.when(F.col("resolved_date").isNotNull(), (F.rand(SEED+34) * 2 + 1).cast("int"))
             .otherwise(F.lit(None).cast("int")))
        df = df.withColumn("subject", F.lit("Case: shipping_delay — delayed shipment"))
    df = df.withColumn("open_hour", (F.rand(SEED+26) * 86400).cast("int"))
    df = df.withColumn("opened_at", (F.col("opened_date").cast("timestamp") + F.expr("make_interval(0,0,0,0,0,0, open_hour)")))
    df = df.withColumn("resolved_at",
        F.when(F.col("resolved_date").isNotNull(), F.col("resolved_date").cast("timestamp")).otherwise(F.lit(None).cast("timestamp")))
    df = df.withColumn("status",
        F.when(F.col("resolved_date").isNotNull(), F.lit("resolved"))
         .when(F.rand(SEED+27) < 0.5, F.lit("open")).otherwise(F.lit("pending")))
    return df.select("id", "account_id", "region", "opened_at", "resolved_at",
                     "status", "priority", "category", "subject", "csat")

N_BASE = 200000
N_EVENT = 95000  # ~30% land in EMEA after the region filter -> ~28K event cases
base = spark.range(0, N_BASE, numPartitions=16)
base = base.withColumn("acc_idx", (F.abs(F.hash(F.col("id") + F.lit(7))) % N_ACCOUNTS))
base = base.withColumn("account_id", F.concat(F.lit("ACC-"), F.lpad(F.col("acc_idx").cast("string"), 6, "0")))
base = build_cases(base, event=False)

evt = spark.range(N_BASE, N_BASE + N_EVENT, numPartitions=8)
evt = evt.withColumn("acc_idx", (F.abs(F.hash(F.col("id") + F.lit(7))) % N_ACCOUNTS))
evt = evt.withColumn("account_id", F.concat(F.lit("ACC-"), F.lpad(F.col("acc_idx").cast("string"), 6, "0")))
evt = build_cases(evt, event=True)

cases_all = base.unionByName(evt)
cases_all = cases_all.withColumn("case_id", F.concat(F.lit("CASE-"), F.lpad(F.col("id").cast("string"), 7, "0")))
cases_out = cases_all.select("case_id", "account_id", "region", "opened_at", "resolved_at",
    "status", "priority", "category", "subject", F.col("csat").cast("int").alias("csat"))
# dirty: null account
cdirty = cases_out.sample(0.004, seed=SEED).withColumn("account_id", F.lit(None).cast("string"))
cases_out2 = cases_out.unionByName(cdirty)
cases_out2.write.mode("overwrite").parquet(f"{VOL}/cases")
print("cases written:", cases_out2.count())

# cleanup temp
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.{SCHEMA}._gen_accounts")
print("DONE")
