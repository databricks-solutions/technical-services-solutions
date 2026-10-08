# Bronze — streaming ingestion (Auto Loader) + data-quality expectations.
#
# The raw landing volume path is passed in as a pipeline configuration value
# (`demo.volume_path`) — SDP SQL `read_files(...)` can't interpolate conf vars,
# so bronze is authored in Python where `spark.conf.get(...)` works. This keeps
# the path correct by resolving catalog/schema through the schema resource.
import dlt
from pyspark.sql import SparkSession

spark = SparkSession.getActiveSession()
VOL = spark.conf.get("demo.volume_path")


def _read(subpath):
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.inferColumnTypes", "true")
        .load(f"{VOL}/{subpath}")
    )


@dlt.table(name="bronze_accounts",
           comment="Raw CRM accounts landed by Lakeflow Connect (Salesforce)")
@dlt.expect("valid_region", "region IN ('NA','EMEA','APAC','LATAM')")
@dlt.expect_or_drop("valid_arr", "arr_usd > 0")
@dlt.expect_or_drop("has_renewal", "renewal_date IS NOT NULL")
def bronze_accounts():
    return _read("accounts")


@dlt.table(name="bronze_orders",
           comment="Raw ERP order/fulfillment events")
@dlt.expect_or_drop("has_account", "account_id IS NOT NULL")
@dlt.expect_or_drop("valid_amount", "amount_usd >= 0")
@dlt.expect("promised_set", "promised_ship_date IS NOT NULL")
def bronze_orders():
    return _read("orders")


@dlt.table(name="bronze_cases",
           comment="Raw support cases landed by Lakeflow Connect (Zendesk)")
@dlt.expect_or_drop("has_account", "account_id IS NOT NULL")
@dlt.expect("valid_status", "status IN ('open','pending','resolved')")
@dlt.expect_or_drop("opened_not_null", "opened_at IS NOT NULL")
def bronze_cases():
    return _read("cases")
