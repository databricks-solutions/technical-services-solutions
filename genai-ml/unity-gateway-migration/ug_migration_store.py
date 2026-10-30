"""Delta storage for the Unity Gateway migration app (scan and apply runs).

Used by the scan and apply job notebooks. Each run gets one metadata row plus one row per item
(plan row, code reference, caller, readiness item, apply result) with the item as JSON, so the
schema doesn't change when the toolkit adds fields.

Tables (in the snapshot catalog and schema):
  ug_migration_scans        one row per workspace scan
  ug_migration_scan_items   run_id, item_type, seq, payload (JSON)
  ug_migration_applies      one row per apply / dry run / rollback
  ug_migration_apply_items  apply_id, seq, payload (JSON)
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

SCAN_COLUMNS = {
    "run_id": "STRING", "job_run_id": "STRING", "requested_by": "STRING", "workspace_url": "STRING",
    "workspace_id": "STRING", "status": "STRING", "readiness": "STRING", "endpoints": "BIGINT",
    "client_references": "BIGINT", "traffic_status": "STRING", "days": "BIGINT", "target_catalog": "STRING",
    "target_schema": "STRING", "scan_roots": "STRING", "toolkit_version": "STRING", "error": "STRING",
    "started_at": "TIMESTAMP", "finished_at": "TIMESTAMP",
}
APPLY_COLUMNS = {
    "apply_id": "STRING", "job_run_id": "STRING", "requested_by": "STRING", "scan_run_id": "STRING",
    "mode": "STRING", "endpoints": "STRING", "target_catalog": "STRING", "target_schema": "STRING",
    "rollback_of": "STRING", "status": "STRING", "summary": "STRING", "error": "STRING",
    "toolkit_version": "STRING", "started_at": "TIMESTAMP", "finished_at": "TIMESTAMP",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _lit(v, typ: str) -> str:
    if v is None or v == "":
        return "NULL"
    if typ == "BIGINT":
        return str(int(float(v)))
    if typ == "TIMESTAMP":
        return f"TIMESTAMP '{v}'"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def q(schema: str) -> str:
    """Backtick-quote a catalog.schema name (hyphens and other characters are allowed in UC names)."""
    return ".".join("`" + p.replace("`", "``") + "`" for p in schema.split("."))


def retry(fn, attempts: int = 4):
    """Retry a Delta write that lost a concurrent-commit race."""
    import time
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # ConcurrentAppendException and friends
            if i == attempts - 1 or "Concurrent" not in type(e).__name__ + str(e)[:200]:
                raise
            time.sleep(2 * (i + 1))


def ensure_tables(spark, schema: str) -> None:
    schema = q(schema)
    for name, cols in (("ug_migration_scans", SCAN_COLUMNS), ("ug_migration_applies", APPLY_COLUMNS)):
        ddl = ", ".join(f"{c} {t}" for c, t in cols.items())
        spark.sql(f"CREATE TABLE IF NOT EXISTS {schema}.{name} ({ddl}) "
                  "COMMENT 'Unity Gateway migration app (prototype)'")
        have = {r["col_name"] for r in spark.sql(f"DESCRIBE TABLE {schema}.{name}").collect()}
        for c, t in cols.items():
            if c not in have:
                spark.sql(f"ALTER TABLE {schema}.{name} ADD COLUMNS ({c} {t})")
    for name, key in (("ug_migration_scan_items", "run_id STRING, item_type STRING"),
                      ("ug_migration_apply_items", "apply_id STRING")):
        spark.sql(f"CREATE TABLE IF NOT EXISTS {schema}.{name} ({key}, seq BIGINT, payload STRING) "
                  "COMMENT 'Unity Gateway migration app items (prototype)'")


def upsert(spark, schema: str, table: str, cols: dict, key: str, values: dict) -> None:
    """Insert or update one metadata row (only the given columns change)."""
    schema = q(schema)
    present = {c: v for c, v in values.items() if c in cols}
    src = ", ".join(f"{_lit(v, cols[c])} AS {c}" for c, v in present.items())
    sets = ", ".join(f"t.{c} = s.{c}" for c in present if c != key)
    ins_cols = ", ".join(present)
    ins_vals = ", ".join(f"s.{c}" for c in present)
    retry(lambda: spark.sql(
        f"MERGE INTO {schema}.{table} t USING (SELECT {src}) s ON t.{key} = s.{key} "
        f"WHEN MATCHED THEN UPDATE SET {sets} WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})"))


def _write_items(spark, schema: str, table: str, rows: list[tuple]) -> None:
    if not rows:
        return
    from pyspark.sql.types import LongType, StringType, StructField, StructType

    if table == "ug_migration_scan_items":
        st = StructType([StructField("run_id", StringType()), StructField("item_type", StringType()),
                         StructField("seq", LongType()), StructField("payload", StringType())])
    else:
        st = StructType([StructField("apply_id", StringType()), StructField("seq", LongType()),
                         StructField("payload", StringType())])
    df = spark.createDataFrame(rows, st)
    retry(lambda: df.write.mode("append").saveAsTable(f"{q(schema)}.{table}"))


def _csv(path: str) -> list[dict]:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_scan_items(spark, schema: str, run_id: str, out_dir: str) -> dict:
    """Load a planner output folder into ug_migration_scan_items; returns the readiness dict."""
    retry(lambda: spark.sql(f"DELETE FROM {q(schema)}.ug_migration_scan_items WHERE run_id = {_lit(run_id, 'STRING')}"))
    rows: list[tuple] = []
    for item_type, fname in (("plan", "migration_plan.csv"), ("ref", "client_references.csv"),
                             ("caller", "callers.csv"), ("provider", "provider_services.csv")):
        for i, r in enumerate(_csv(os.path.join(out_dir, fname))):
            rows.append((run_id, item_type, i, json.dumps(r)))
    ready = json.load(open(os.path.join(out_dir, "readiness.json")))
    rows.append((run_id, "readiness", 0, json.dumps(ready)))
    for name in ("SUMMARY.md", "READINESS.md", "CODE_FIXES.md"):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            rows.append((run_id, "doc:" + name, 0, json.dumps({"markdown": open(p).read()})))
    _write_items(spark, schema, "ug_migration_scan_items", rows)
    return ready


def write_apply_items(spark, schema: str, apply_id: str, results: list[dict]) -> None:
    retry(lambda: spark.sql(f"DELETE FROM {q(schema)}.ug_migration_apply_items WHERE apply_id = {_lit(apply_id, 'STRING')}"))
    _write_items(spark, schema, "ug_migration_apply_items",
                 [(apply_id, i, json.dumps(r, default=str)) for i, r in enumerate(results)])


def apply_run(spark, schema: str, apply_id: str) -> dict | None:
    rows = spark.sql(f"SELECT mode, status, job_run_id FROM {q(schema)}.ug_migration_applies "
                     f"WHERE apply_id = {_lit(apply_id, 'STRING')}").collect()
    return {"mode": rows[0]["mode"], "status": rows[0]["status"], "job_run_id": rows[0]["job_run_id"]} if rows else None


def effective_status(w, status: str | None, job_run_id: str | None) -> str | None:
    """A row left at RUNNING by a job that was killed counts as FAILED once its job run has ended."""
    if status != "RUNNING" or not str(job_run_id or "").isdigit():
        return status
    try:
        st = w.jobs.get_run(int(job_run_id)).state
    except Exception:
        return status
    ended = st and st.life_cycle_state and st.life_cycle_state.value in ("TERMINATED", "INTERNAL_ERROR", "SKIPPED")
    return "FAILED" if ended else status


def run_exists(spark, schema: str, table: str, key: str, value: str) -> bool:
    return bool(spark.sql(f"SELECT 1 FROM {q(schema)}.{table} WHERE {key} = {_lit(value, 'STRING')} LIMIT 1").collect())


def already_rolled_back(spark, schema: str, apply_id: str, w=None, exclude: str | None = None) -> bool:
    """True if a rollback of this run succeeded or is still really running (killed ones don't count)."""
    rows = spark.sql(f"SELECT apply_id, status, job_run_id FROM {q(schema)}.ug_migration_applies WHERE mode = 'rollback' "
                     f"AND rollback_of = {_lit(apply_id, 'STRING')} AND status IN ('RUNNING', 'SUCCEEDED')").collect()
    return any(r["apply_id"] != exclude and
               (r["status"] == "SUCCEEDED" or w is None or effective_status(w, r["status"], r["job_run_id"]) == "RUNNING")
               for r in rows)


def apply_log_from_items(spark, schema: str, apply_id: str, path: str, durable_log: str | None = None) -> int:
    """Rebuild an apply log file (for rollback) from a stored apply run.

    Uses the stored result rows; if the execute run was interrupted before it stored them, falls back to the
    durable log the run wrote as it went (durable_log)."""
    rows = spark.sql(f"SELECT payload FROM {q(schema)}.ug_migration_apply_items "
                     f"WHERE apply_id = {_lit(apply_id, 'STRING')} ORDER BY seq").collect()
    entries = [json.loads(r["payload"]) for r in rows]
    if not any(e.get("execute") and e.get("action") in ("created", "creating") for e in entries) \
            and durable_log and os.path.exists(durable_log):
        entries = [json.loads(l) for l in open(durable_log) if l.strip()]
    n = 0
    with open(path, "w") as f:
        for entry in entries:
            if entry.get("execute") and entry.get("action") in ("created", "creating"):
                f.write(json.dumps(entry) + "\n")
                n += 1
    return n


def protected_objects(spark, schema: str, apply_id: str) -> set[tuple[str, str]]:
    """Objects other execute runs (not rolled back) still depend on, so a rollback must keep them.

    A run depends on what it created, and on provider services it reused for model services it created
    (a later wave). Re-running the same selection only finds everything existing, so it protects nothing."""
    s = q(schema)
    rows = spark.sql(f"""
        SELECT i.apply_id, i.payload FROM {s}.ug_migration_apply_items i JOIN {s}.ug_migration_applies a USING (apply_id)
        WHERE a.mode = 'execute' AND a.apply_id <> {_lit(apply_id, 'STRING')}
          AND NOT EXISTS (SELECT 1 FROM {s}.ug_migration_applies r
                          WHERE r.mode = 'rollback' AND r.rollback_of = a.apply_id AND r.status = 'SUCCEEDED')
    """).collect()
    runs: dict[str, list[dict]] = {}
    for r in rows:
        e = json.loads(r["payload"])
        if e.get("execute"):
            runs.setdefault(r["apply_id"] if "apply_id" in r else "", []).append(e)
    out = set()
    for entries in runs.values():
        made_service = any(e.get("type") == "model_service" and e.get("action") in ("created", "creating")
                           for e in entries)
        for e in entries:
            if e.get("action") in ("created", "creating") or \
                    (made_service and e.get("type") == "model_provider_service" and e.get("action") == "exists"):
                out.add((e.get("type"), e.get("name")))
    return out


now = _now
