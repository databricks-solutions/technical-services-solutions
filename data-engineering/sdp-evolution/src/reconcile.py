"""Schema-evolution reconciliation for the SDP orders silver table.

Bronze ingests with Auto Loader in rescue mode, so any columns that get
renamed, retyped, or newly added after v1 land in the `_rescued_data` column
instead of breaking the pipeline. `reconcile` recovers those values back out of
`_rescued_data` via `coalesce`: for each business column it prefers the base
column and falls back to the rescued JSON. This keeps silver whole after drift
WITHOUT a full refresh - old v1 rows and new v2 rows both resolve correctly.

Null handling: `from_json` of a null `_rescued_data` yields a null struct, so
every field access is null and `coalesce` falls back to the base column. That
is exactly right for clean v1 rows that were never rescued.
"""

from pyspark.sql import functions as F, DataFrame

RESCUE_SCHEMA = "customer_name string, amount double, loyalty_tier string"


def reconcile(df: DataFrame) -> DataFrame:
    r = F.from_json(F.col("_rescued_data"), RESCUE_SCHEMA)
    return df.select(
        "order_id",
        F.coalesce(F.col("cust_name"), r["customer_name"]).alias("customer_name"),
        F.coalesce(F.col("amount").cast("double"), r["amount"]).alias("amount"),
        r["loyalty_tier"].alias("loyalty_tier"),
        "order_ts",
    )
