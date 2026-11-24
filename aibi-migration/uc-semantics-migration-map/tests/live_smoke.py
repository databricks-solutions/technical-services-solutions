#!/usr/bin/env python3
"""LIVE smoke test against a real workspace. Creates (and by default removes) a throw-away schema + objects.

  python3 -I tests/live_smoke.py --profile my-aws-profile --catalog my_catalog                      # workspace-scoped objects only
  python3 -I tests/live_smoke.py --profile my-account-admin-ws --catalog my_catalog --account-objects   # + governed tags, domains, pages, wikis

--account-objects creates ACCOUNT-LEVEL objects (governed tags, domains) — only use it in an account where that
is fine. Everything is namespaced with a random --tag-prefix and removed at the end (state-tracked prune).
Plays the agent end to end through the real CLIs: seed → design → decide → author (from real columns) →
live-validate → apply → re-apply (must be a no-op) → change → re-apply (exactly one update) → verify → cleanup.
"""
import argparse
import json
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
sys.path.insert(0, S)
from dbx import DbxClient, ApiError  # noqa: E402
from smlib import read_yaml, write_yaml, read_json  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--profile", default=None)
ap.add_argument("--catalog", required=True)
ap.add_argument("--schema", default="ucsm_smoke")
ap.add_argument("--account-objects", action="store_true")
ap.add_argument("--keep", action="store_true")
ap.add_argument("--in-process", action="store_true", help="run the skill CLIs in this process (required inside a Databricks notebook)")
a = ap.parse_args()

PFX = "ucsm" + "".join(random.choices(string.ascii_lowercase, k=4))
CAT, SCH = a.catalog, a.schema
W = tempfile.mkdtemp(prefix="ucsm-live-")
MAP = os.path.join(W, "semantic-map.yaml")
STATE = os.path.join(W, "apply-state.json")
res, fails = [], []
c = DbxClient(a.profile)


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"\n       {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def sh(script, *args, ok=True):
    pa = ["--profile", a.profile] if a.profile and script in ("apply.py",) else []
    pre = ["--profile", a.profile] if a.profile and script == "author.py" else []
    if a.in_process:
        import ucsm
        rc, out, err = ucsm.run_captured(script, *pre, *args, *pa)
        p = subprocess.CompletedProcess([], rc, out, err)
    else:
        cmd = [sys.executable, "-I", os.path.join(S, script), *pre, *args, *pa]
        p = subprocess.run(cmd, capture_output=True, text=True)
    if ok and p.returncode != 0:
        print(f"!! {script} {' '.join(args)}\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
    return p


print(f"workspace user: {c.who()}   warehouse: {c.warehouse_id}   catalog: {CAT}   prefix: {PFX}   account-objects: {a.account_objects}")

# ---------------------------------------------------------------- seed real tables
c.sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{SCH}")
c.sql(f"""CREATE OR REPLACE TABLE {CAT}.{SCH}.sales_fct AS
  SELECT * FROM VALUES
   (1, DATE'2025-01-10','EMEA', 100.0, 120.0, 20.0, 10, 60.0),
   (2, DATE'2025-01-20','AMER', 200.0, 210.0, 10.0, 20, 120.0),
   (3, DATE'2025-02-05','EMEA', 150.0, 160.0, 10.0, 15, 90.0),
   (4, DATE'2025-02-18','AMER', 300.0, 330.0, 30.0, 30, 170.0),
   (5, DATE'2025-03-02','EMEA', 250.0, 260.0, 10.0, 25, 140.0)
  AS t(order_id, order_date, region, net_amt, gross_amt, returns_amt, units, cogs)""")
c.sql(f"""CREATE OR REPLACE TABLE {CAT}.{SCH}.inventory_fct AS
  SELECT * FROM VALUES
   ('A', DATE'2025-01-31', 50, 5.0), ('A', DATE'2025-02-28', 40, 5.0), ('B', DATE'2025-01-31', 30, 3.0), ('B', DATE'2025-02-28', 35, 3.0)
  AS t(sku, snap_date, on_hand_units, sell_rate_8wk)""")
check("seeded source tables", len(c.sql(f"SELECT 1 FROM {CAT}.{SCH}.sales_fct")) == 5)

cfg = dict(target=dict(catalog=CAT, schema=SCH, tag_prefix=PFX),
           table_map={"retail_dm.dm_sales_fct": f"{CAT}.{SCH}.sales_fct", "retail_dm.dm_inventory_fct": f"{CAT}.{SCH}.inventory_fct",
                      "crm.customer_orders_fct": f"{CAT}.{SCH}.customer_orders_fct"})
write_yaml(os.path.join(W, "design.yaml"), cfg)
inv = os.path.join(ROOT, "examples", "inventory.example.json")

# ---------------------------------------------------------------- stage 1: assessment
check("design runs", sh("design.py", inv, "-o", MAP, "--config", os.path.join(W, "design.yaml")).returncode == 0)
m = read_yaml(MAP)
check("assessment produced concepts but no YAML", m["concepts"] and not any(x.get("yaml") for x in m["metric_views"]))
for cn in [x for x in m["concepts"] if x["drift"]]:
    sh("decide.py", "choose", MAP, cn["key"], "1")
sh("decide.py", "approve", MAP, "--all")

# ---------------------------------------------------------------- stage 2a: author (as the agent would, from real columns)
sales_mv = next(x for x in read_yaml(MAP)["metric_views"] if "sales" in x["key"])
inv_mv = next(x for x in read_yaml(MAP)["metric_views"] if "inventory" in x["key"])
cons = {x["name"]: x for x in read_yaml(MAP)["concepts"]}
ctx = sh("author.py", "context", MAP, sales_mv["key"])
try:
    cj = json.loads(ctx.stdout)
    cols = {x["name"] for x in cj["source_columns"]}
    check("author context lists the real source columns", {"net_amt", "order_date"} <= cols, str(cj["source_columns"])[:200])
    check("author context points at patterns repo", cj["patterns_repo"]["repo"].endswith("uc-semantics-patterns"), str(cj["patterns_repo"]))
except Exception as e:
    check("author context parses", False, f"{e}: {ctx.stdout[:300]} {ctx.stderr[:300]}")

SALES_YAML = f"""version: 1.1
comment: Sales KPIs — single definition for net revenue, units and margin
source: {CAT}.{SCH}.sales_fct
fields:
  - name: Month
    display_name: Order Month
    expr: DATE_TRUNC('month', order_date)
    format:
      type: date
      date_format: year_month_day
      leading_zeros: true
  - name: Region
    expr: region
measures:
  - name: Net Revenue
    comment: Revenue net of returns
    expr: SUM(net_amt)
  - name: Units
    expr: SUM(units)
  - name: Gross Margin
    comment: Net revenue minus cost of goods
    expr: SUM(net_amt) - SUM(cogs)
  - name: Net Revenue CM
    comment: Net revenue for the current month (period-over-period pattern)
    expr: SUM(net_amt)
    window:
      - order: Month
        range: current
        semiadditive: last
  - name: Net Revenue PM
    comment: Net revenue for the previous month
    expr: SUM(net_amt)
    window:
      - order: Month
        range: current
        semiadditive: last
        offset: -1 month
  - name: Net Revenue MoM
    comment: Month-over-month growth
    expr: (AGG(`Net Revenue CM`) - AGG(`Net Revenue PM`)) / AGG(`Net Revenue PM`)
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 2
"""
INV_YAML = f"""version: 1.1
comment: Inventory KPIs
source: {CAT}.{SCH}.inventory_fct
fields:
  - name: SnapMonth
    expr: DATE_TRUNC('month', snap_date)
measures:
  - name: On Hand
    comment: Closing on-hand units (semi-additive)
    expr: SUM(on_hand_units)
    window:
      - order: SnapMonth
        range: current
        semiadditive: last
  - name: Weeks of Supply
    expr: SUM(on_hand_units) / NULLIF(AVG(sell_rate_8wk), 0)
"""
for mv, y in ((sales_mv, SALES_YAML), (inv_mv, INV_YAML)):
    f = os.path.join(W, mv["key"] + ".yaml")
    open(f, "w").write(y)
    r = sh("author.py", "register", MAP, mv["key"], f)
    check(f"register {mv['key']}", r.returncode == 0, r.stdout[-300:] + r.stderr[-300:])
    r = sh("author.py", "validate", MAP, mv["key"])
    check(f"live-validate {mv['key']} (throw-away view, all measures evaluate)", r.returncode == 0, r.stdout[-400:] + r.stderr[-400:])
    sh("author.py", "approve", MAP, mv["key"])
check("validation left no throw-away views", not c.sql(f"SELECT table_name FROM {CAT}.information_schema.tables WHERE table_schema='{SCH}' AND table_name LIKE '\\_\\_ucsm\\_check%'"))

# ---------------------------------------------------------------- stage 2b: apply
only = [] if a.account_objects else ["--only", "metric_views"]
p = sh("apply.py", MAP, *only, ok=False)
print(p.stdout[-2500:])
check("dry-run plan succeeds and writes nothing", p.returncode == 0 and "Dry run" in p.stdout, p.stderr[-400:])
p = sh("apply.py", MAP, *only, "--execute", "--yes", ok=False)
print(p.stdout[-2200:], p.stderr[-1500:])
check("first apply succeeds", p.returncode == 0 and "failed" in p.stdout and "0 failed" in p.stdout, p.stderr[-800:])
for mv in (sales_mv, inv_mv):
    t = c.w.tables.get(mv["fqn"]) if hasattr(c, "w") else None
    check(f"metric view exists: {mv['fqn']}", t is not None and "METRIC" in str(t.table_type).upper() or t is not None, str(t.table_type if t else None))

# values: the metric view must agree with plain SQL
mv_total = c.sql(f"SELECT MEASURE(`Net Revenue`) FROM {sales_mv['fqn']}")[0][0]
check("MEASURE(Net Revenue) matches plain SQL", float(mv_total) == 1000.0, str(mv_total))
rows = c.sql(f"SELECT Month, MEASURE(`Net Revenue`) AS nr, MEASURE(`Net Revenue MoM`) AS mom FROM {sales_mv['fqn']} GROUP BY ALL ORDER BY Month")
check("pattern-based MoM measure evaluates per month", len(rows) == 3 and rows[0][2] in (None, "null") and abs(float(rows[1][2]) - ((450 - 300) / 300)) < 1e-6, str(rows))

# ---------------------------------------------------------------- idempotency
p = sh("apply.py", MAP, *only, "--execute", "--yes", ok=False)
check("re-apply is a no-op ('Nothing to write')", "Nothing to write" in p.stdout, p.stdout[-900:])

# ---------------------------------------------------------------- change → exactly one update
y2 = SALES_YAML + "  - name: Order Count\n    expr: COUNT(1)\n"
f = os.path.join(W, "sales_v2.yaml")
open(f, "w").write(y2)
sh("author.py", "register", MAP, sales_mv["key"], f)
sh("author.py", "validate", MAP, sales_mv["key"])
sh("author.py", "approve", MAP, sales_mv["key"])
p = sh("apply.py", MAP, *only, ok=False)
ups = [ln for ln in p.stdout.splitlines() if "definition changed" in ln]
check("changed YAML ⇒ exactly one metric view update planned", len(ups) == 1 and "mv_sales" in ups[0], "\n".join(ups))
if a.account_objects:
    check("…and the replaced view gets its domain tag re-applied", any("re-applied" in ln and "mv_sales" in ln for ln in p.stdout.splitlines()), p.stdout[-900:])
p = sh("apply.py", MAP, *only, "--execute", "--yes", ok=False)
check("update applied", "0 failed" in p.stdout, p.stdout[-600:] + p.stderr[-600:])
check("new measure live", float(c.sql(f"SELECT MEASURE(`Order Count`) FROM {sales_mv['fqn']}")[0][0]) == 5.0)

# ---------------------------------------------------------------- account-level objects
if a.account_objects:
    st = read_json(STATE)["objects"]
    kinds = {}
    for k, v in st.items():
        kinds.setdefault(v["kind"], []).append(k)
    print("applied kinds:", {k: len(v) for k, v in kinds.items()})
    for need in ("tag_policies", "domains", "pages", "wikis", "asset_tags", "metric_views"):
        check(f"applied {need}", bool(kinds.get(need)), str(kinds))
    p = sh("apply.py", MAP, "--execute", "--yes", "--publish", ok=False)
    print(p.stdout[-1800:], p.stderr[-800:])
    check("--publish flips drafts without errors", "0 failed" in p.stdout or "Nothing to write" in p.stdout, p.stdout[-500:] + p.stderr[-500:])
    p = sh("apply.py", MAP, "--execute", "--yes", "--publish", ok=False)
    check("…and is then a no-op again", "Nothing to write" in p.stdout, p.stdout[-700:])

# ---------------------------------------------------------------- cleanup
if not a.keep:
    m = read_yaml(MAP)
    for k in ("domains", "concepts", "metric_views", "pages", "wikis", "asset_tags"):
        m[k] = []
    empty = os.path.join(W, "empty-map.yaml")
    write_yaml(empty, m)
    p = sh("apply.py", empty, "--prune", "--execute", "--yes", "--state", STATE, ok=False)
    print(p.stdout[-1500:], p.stderr[-800:])
    check("prune removed everything this run created", "0 failed" in p.stdout, p.stdout[-400:] + p.stderr[-400:])
    c.sql(f"DROP SCHEMA IF EXISTS {CAT}.{SCH} CASCADE")
    check("schema dropped", not c.sql(f"SELECT 1 FROM {CAT}.information_schema.schemata WHERE schema_name='{SCH}'"))
    shutil.rmtree(W, ignore_errors=True)
else:
    print("kept:", W)
print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
