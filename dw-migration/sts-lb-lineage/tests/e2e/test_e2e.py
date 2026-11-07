"""End-to-end: run the Lakebridge Analyzer on the synthetic sources in sources/<slug>/, then build
the lineage. One case per analyzer source technology.

Each case pins what the Lakebridge Analyzer gives today:
- "lineage": these table edges (and job edges) must appear.
- "orchestration": job-to-job edges only; table edges would be news.
- "inventory": programs are listed, but no edges. A failure here can mean a newer analyzer
  now finds lineage; then update the case and the README table.
- "none": the analyzer finds nothing in the sample (the format is not known well enough).

Run: uv run -p 3.12 --no-project --with-editable '.[test,analyzer]' pytest -q -m e2e
"""

import json
from pathlib import Path

import pytest

from sts_lb_lineage.core import main

SOURCES = Path(__file__).parent / "sources"

SQL = {
    ("raw.sales", "stg.sales_clean", "data"),
    ("raw.customers", "stg.sales_clean", "data"),
    ("stg.sales_clean", "dw.fact_sales", "data"),
}
NO_FIRST_JOIN_TABLE = SQL - {("raw.sales", "stg.sales_clean", "data")}
NO_INSERT_OVERWRITE = SQL - {("stg.sales_clean", "dw.fact_sales", "data")}

# slug, platform, --extension, status, required edges (from name, to name, kind), note
CASES = [
    ("athena", "Athena", None, "lineage", SQL, ""),
    (
        "bigquery",
        "BigQuery",
        None,
        "lineage",
        {
            ("stg.sales_clean", "dw.fact_sales", "data"),
            ("s", "stg.sales_clean", "data"),
        },
        "backtick names: the join source comes back as its alias `s`, raw.customers is lost",
    ),
    (
        "impala",
        "Cloudera (Impala)",
        None,
        "lineage",
        NO_INSERT_OVERWRITE,
        "INSERT OVERWRITE TABLE is not seen",
    ),
    (
        "greenplum",
        "Greenplum",
        None,
        "lineage",
        NO_FIRST_JOIN_TABLE,
        "with DISTRIBUTED BY, the first join table is lost",
    ),
    (
        "hive",
        "Hive",
        None,
        "lineage",
        NO_INSERT_OVERWRITE,
        "INSERT OVERWRITE TABLE is not seen",
    ),
    ("db2", "IBM DB2", None, "lineage", SQL, ""),
    (
        "netezza",
        "Netezza",
        None,
        "lineage",
        NO_FIRST_JOIN_TABLE,
        "with DISTRIBUTE ON, the first join table is lost",
    ),
    ("oracle", "Oracle", None, "lineage", SQL, ""),
    ("presto", "Presto", None, "lineage", SQL, ""),
    ("redshift", "Redshift", None, "lineage", SQL, ""),
    (
        "snowflake",
        "Snowflake",
        None,
        "lineage",
        {("stg.sales_clean", "dw.fact_sales", "data")},
        "CREATE OR REPLACE TRANSIENT TABLE ... AS SELECT is not seen",
    ),
    ("mssql", "MS SQL Server", None, "lineage", SQL, ""),
    ("synapse", "Synapse", None, "lineage", SQL, ""),
    ("teradata", "Teradata", None, "lineage", SQL, ""),
    (
        "vertica",
        "Vertica",
        None,
        "lineage",
        NO_FIRST_JOIN_TABLE,
        "with SEGMENTED BY, the first join table is lost",
    ),
    (
        "pyspark",
        "PySpark",
        None,
        "lineage",
        {
            ("raw.orders", "stg.orders_clean", "data"),
            ("stg.orders_clean", "dw.fact_orders", "data"),
            ("raw.customers", "dw.fact_orders", "data"),
            ("dw.fact_orders", "dw.fact_orders_daily", "data"),
        },
        "only SQL inside spark.sql(); DataFrame API calls give no lineage",
    ),
    (
        "pig",
        "PIG",
        None,
        "lineage",
        {
            ("raw.orders", "stg.orders_clean", "data"),
            ("stg.orders_clean", "dw.fact_orders", "data"),
        },
        "job-level relations, so inputs x outputs over-link",
    ),
    (
        "sas",
        "SAS",
        None,
        "lineage",
        {
            ("raw.orders", "stg.orders_clean", "data"),
            ("stg.orders_clean", "dw.fact_orders", "data"),
            ("raw.customers", "dw.fact_orders", "data"),
        },
        "PROC SQL; DATA step SET was not captured in testing",
    ),
    (
        "infa-pc",
        "Informatica - PC",
        None,
        "lineage",
        {
            ("orders", "orders_clean", "data"),
            ("orders_clean", "fact_orders", "data"),
            ("wf_orders", "s_m_load_orders", "orchestration"),
            ("s_m_load_orders", "m_load_orders", "orchestration"),
        },
        "table names lose their schema; Windows-1252 XML exports fail on macOS",
    ),
    (
        "ssis",
        "SSIS",
        None,
        "lineage",
        {("stg.orders_clean", "dw.fact_orders", "data")},
        "the OLE DB destination is reported as a read, so raw.orders -> stg.orders_clean is lost",
    ),
    (
        "pentaho",
        "PentahoDI",
        None,
        "lineage",
        {("raw.orders", "stg.orders_clean", "data")},
        "<schema> is ignored (use schema.table in <table>); .kjb gives no job links",
    ),
    (
        "oozie",
        "Oozie",
        None,
        "orchestration",
        {
            (
                "workflow.job_load_orders.load_stg",
                "workflow.job_load_orders.load_fact",
                "orchestration",
            )
        },
        "only workflow.xml is read; Hive scripts and inline queries give no tables",
    ),
    (
        "adf",
        "ADF",
        None,
        "orchestration",
        {
            ("pl_parent", "pl_clean_orders", "orchestration"),
            ("pl_parent", "pl_load_fact", "orchestration"),
        },
        "Execute Pipeline links only; Copy activities and datasets give no tables",
    ),
    (
        "jupyter",
        "Jupyter Notebook",
        None,
        "inventory",
        set(),
        "spark.sql and %%sql cells give no relations",
    ),
    (
        "sqoop",
        "SQOOP",
        None,
        "inventory",
        set(),
        "needs .txt files; import/export give no relations",
    ),
    (
        "spss",
        "SPSS",
        "sps",
        "inventory",
        set(),
        "needs --extension sps; GET DATA /SQL is not read",
    ),
    (
        "hana",
        "SAPHANA - CalcViews",
        None,
        "inventory",
        set(),
        "nodes are counted, but no tables",
    ),
    ("ssrs", "SSRS", None, "inventory", set(), "dataset queries give no relations"),
    (
        "alteryx",
        "Alteryx",
        None,
        "inventory",
        set(),
        "input tables are read, output tables are not",
    ),
    (
        "bods",
        "BODS",
        None,
        "inventory",
        set(),
        "XML export only (.atl fails); no table relations",
    ),
    (
        "datastage",
        "Datastage",
        "xml",
        "inventory",
        set(),
        "needs --extension xml (XML export; .dsx text fails); stages are counted, no tables",
    ),
    (
        "iics",
        "Informatica Cloud",
        "zip",
        "none",
        set(),
        "needs --extension zip; the sample export package is not recognized",
    ),
    ("talend", "Talend", None, "none", set(), "the sample .item files are not parsed"),
    ("abinitio", "ABInitio", None, "none", set(), "the sample .mp file is not parsed"),
    (
        "infa-bde",
        "Informatica - Big Data Edition",
        None,
        "none",
        set(),
        "the sample mapping export is not parsed",
    ),
    (
        "odi",
        "Oracle Data Integrator",
        None,
        "none",
        set(),
        "the sample export is not parsed",
    ),
]

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module", autouse=True)
def _analyzer():
    pytest.importorskip(
        "databricks.labs.bladespector.analyzer", reason="needs the [analyzer] extra"
    )


@pytest.mark.parametrize(
    ("slug", "platform", "ext", "status", "edges", "note"),
    CASES,
    ids=[c[0] for c in CASES],
)
def test_technology(tmp_path, slug, platform, ext, status, edges, note):
    src = SOURCES / slug
    argv = [
        *map(
            str,
            ["--run", src, "--platform", platform, "-o", tmp_path, "--format", "json"],
        )
    ]
    main([*argv, *(["--extension", ext] if ext else [])])
    raw = (tmp_path / "lineage.json").read_text()
    d = json.loads(raw)
    names = {n["id"]: n["name"].lower() for n in d["nodes"]}  # analyzers differ in case
    got = {(names[e["from"]], names[e["to"]], e["kind"]) for e in d["edges"]}
    assert edges <= got, f"{platform}: missing {sorted(edges - got)} ({note})"
    if status == "orchestration":
        assert not any(k == "data" for *_, k in got), (
            f"{platform}: table lineage appeared, update the case"
        )
    if status == "inventory":
        assert d["programs"] and not got, (
            f"{platform}: inventory-only case changed, update it"
        )
    if status == "none":
        assert not d["programs"], (
            f"{platform}: the analyzer now parses the sample, update the case"
        )
    assert str(src.resolve()) not in raw and "/private/" not in raw, (
        "local paths leaked into lineage.json"
    )


# Larger, multi-file estates: several processes, shared tables, MERGE, CTEs, temp tables, cursors,
# dynamic SQL. Each pins edges, process count, shared tables, and cycles.
# slug, platform, extra CLI flags, required edges, processes, min shared tables, cycles, note
COMPLEX = [
    (
        "infa-pc-complex",
        "Informatica - PC",
        ["--collapse-instances"],
        {
            ("customer", "stg_customer", "data"),
            ("region", "stg_customer", "data"),
            ("stg_customer", "dim_customer", "data"),
            ("customer_score", "dim_customer", "data"),
            ("dim_customer", "fact_sales", "data"),
            ("stg_sales", "fact_sales", "data"),
            ("fact_sales", "customer_score", "data"),
            ("wf_customer", "s_m_stg_customer", "orchestration"),
        },
        2,
        2,
        1,
        "2 workflows, 5 mappings, lookups and an SQ join override; the workflows feed each other",
    ),
    (
        "ssis-complex",
        "SSIS",
        [],
        {
            ("raw.customer", "stg.customer_clean", "data"),
            ("stg.customer_clean", "dw.dim_customer", "data"),
            ("dw.dim_customer", "dw.fact_sales", "data"),
            ("stg.sales_clean", "dw.fact_sales", "data"),
            ("dw.fact_sales", "mart.sales_summary", "data"),
        },
        4,
        3,
        0,
        "master package with Execute Package tasks (no job links from the analyzer)",
    ),
    (
        "pyspark-complex",
        "PySpark",
        [],
        {
            ("raw.sales_online", "stg.sales_clean", "data"),
            ("raw.sales_store", "stg.sales_clean", "data"),
            ("dw.fact_sales", "mart.sales_by_region", "data"),
        },
        2,
        1,
        0,
        "CTEs, UNION ALL, MERGE INTO, temp views; the analyzer links per file",
    ),
    (
        "sas-complex",
        "SAS",
        [],
        {
            ("raw.sales", "work.sales_yr", "data"),
            ("work.sales_yr", "stg.sales_clean", "data"),
            ("stg.sales_clean", "work.top_regions", "data"),
            ("work.top_regions", "out.region_summary", "data"),
            ("out.region_summary", "out.region_history", "data"),
        },
        2,
        1,
        0,
        "PROC SQL chains across two programs",
    ),
    (
        "mssql-complex",
        "MS SQL Server",
        [],
        {
            ("raw.orders", "#orders", "data"),
            ("raw.order_lines", "#orders", "data"),
            ("dw.fact_sales", "mart.sales_by_region", "data"),
            ("stg.customer_segment", "mart.top_customers", "data"),
        },
        2,
        1,
        0,
        "procedures with temp tables, CTE, MERGE, cursor, sp_executesql; MERGE targets and CTE names are not resolved",
    ),
    (
        "oracle-complex",
        "Oracle",
        [],
        {
            ("raw.journal_entries", "stg.gl_entries", "data"),
            ("stg.gl_entries", "dw.fact_gl", "data"),
            ("dw.fact_gl", "mart.account_balance", "data"),
        },
        1,
        0,
        0,
        "PL/SQL package with MERGE, cursor loop, EXECUTE IMMEDIATE",
    ),
    (
        "teradata-complex",
        "Teradata",
        [],
        {("dw.dim_customer", "mart.customer_counts", "data")},
        1,
        0,
        0,
        "BTEQ with a volatile table and MERGE; the MERGE is not seen",
    ),
]


@pytest.mark.parametrize(
    ("slug", "platform", "flags", "edges", "processes", "hubs", "cycles", "note"),
    COMPLEX,
    ids=[c[0] for c in COMPLEX],
)
def test_complex_estate(
    tmp_path, slug, platform, flags, edges, processes, hubs, cycles, note
):
    src = SOURCES / slug
    main(
        ["--run", str(src), "--platform", platform, "-o", str(tmp_path)]
        + ["--format", "json,html", *flags]
    )
    raw = (tmp_path / "lineage.json").read_text()
    d = json.loads(raw)
    names = {n["id"]: n["name"].lower() for n in d["nodes"]}
    got = {(names[e["from"]], names[e["to"]], e["kind"]) for e in d["edges"]}
    s = d["insights"]["summary"]
    assert edges <= got, f"{slug}: missing {sorted(edges - got)} ({note})"
    assert (s["processes"], s["cycles"]) == (processes, cycles), f"{slug}: {s}"
    assert s["hubs"] >= hubs, f"{slug}: {s['hubs']} shared tables"
    assert "/private/" not in raw and str(src.resolve()) not in raw
    assert (tmp_path / "lineage.html").stat().st_size > 1_000_000
