"""Delta storage for the Unity Gateway migration app (scan and apply runs).

Used by the scan and apply job notebooks. Each run gets one metadata row plus one row per item
(plan row, code reference, caller, readiness item, apply result) with the item as JSON, so the
schema doesn't change when the toolkit adds fields.

Tables (in the snapshot catalog and schema):
  ug_migration_scans        one row per workspace scan
  ug_migration_scan_items   run_id, item_type, seq, payload (JSON)
  ug_migration_applies      one row per apply / dry run / rollback
  ug_migration_apply_items  apply_id, seq, payload (JSON)

The app (app/backend/main.py) imports this module, so the app and the jobs share one copy of the SQL, the
fingerprints and the rollback rules. Releases put it next to main.py (app/backend).
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone

from ug_migration_apply import (rollback_summary_done, DEFAULT_API_TYPE, DEFAULT_PROMPT, OWNED_ACTIONS, PROBLEM_ACTIONS,
                               ROLLBACK_TYPES, WRITE_LEGACY_OPERATIONS)

SCAN_COLUMNS = {
    "run_id": "STRING", "job_run_id": "STRING", "requested_by": "STRING", "workspace_url": "STRING",
    "workspace_id": "STRING", "status": "STRING", "readiness": "STRING", "endpoints": "BIGINT",
    "client_references": "BIGINT", "traffic_status": "STRING", "days": "BIGINT", "target_catalog": "STRING",
    "target_schema": "STRING", "scan_roots": "STRING", "toolkit_version": "STRING", "error": "STRING",
    "started_at": "TIMESTAMP", "finished_at": "TIMESTAMP",
}
APPLY_COLUMNS = {
    "apply_id": "STRING", "job_run_id": "STRING", "requested_by": "STRING", "scan_run_id": "STRING",
    "mode": "STRING", "operation": "STRING", "endpoints": "STRING", "services": "STRING",
    "api_type": "STRING", "target_catalog": "STRING", "target_schema": "STRING",
    "rollback_of": "STRING", "status": "STRING", "summary": "STRING", "error": "STRING",
    "toolkit_version": "STRING", "fingerprint": "STRING", "started_at": "TIMESTAMP", "finished_at": "TIMESTAMP",
    "dry_run_id": "STRING",  # execute: the dry run it followed (each dry run is good for one execute)
    # Central mode: the workspace the run acted on (blank on rows from before central mode = the hub).
    "workspace_id": "STRING", "workspace_url": "STRING",
}
# The options that decide what an apply run does. An execute must match the dry run it follows on all of them.
FINGERPRINT_KEYS = ("scan_run_id", "endpoints", "target_catalog", "target_schema", "uc_secret_map",
                    "allow_secret_read", "grants", "ack_guardrails", "create_uc_secrets", "target_workspace_id")
FLAG_KEYS = ("allow_secret_read", "grants", "ack_guardrails", "create_uc_secrets")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


_ZONE_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2}|UTC)$")


def _utc(v) -> str:
    """A timestamp string with an explicit UTC offset. The toolkit writes and compares UTC; a string without a zone
    would be read in the session time zone of the job or warehouse, which shifts every window when it isn't UTC."""
    t = str(v).strip()
    if len(t) > 10 and t[10] == "T":  # 2026-11-02T10:00 -> 2026-11-02 10:00 (only the date/time separator)
        t = t[:10] + " " + t[11:]
    if _ZONE_RE.search(t):
        return t
    if len(t) == 10:  # a date: midnight UTC
        t += " 00:00:00"
    elif len(t) == 16:  # minutes only
        t += ":00"
    return t + "+00:00"


def _lit(v, typ: str) -> str:
    if v is None or v == "":
        return "NULL"
    if typ == "BIGINT":
        return str(int(float(v)))
    if typ == "TIMESTAMP":
        return f"TIMESTAMP '{_utc(v)}'"
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


def use_utc(spark) -> None:
    """Run the job's SQL in UTC, so CAST(... AS STRING) of the run times and any zone-less value read the same in
    every job (the writes carry an explicit +00:00 too). A session without conf (the tests' fake) is left as is."""
    conf = getattr(spark, "conf", None)
    if conf is not None:
        conf.set("spark.sql.session.timeZone", "UTC")


def ensure_tables(spark, schema: str) -> None:
    """Create the tables, and add any column this version has that an older table lacks (ALTER TABLE ADD COLUMNS)."""
    use_utc(spark)
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
    # workspace_id: the workspace the run acted on (central mode), so a rollback or resume acts there too.
    rows = spark.sql(f"SELECT mode, operation, status, job_run_id, workspace_id FROM {q(schema)}.ug_migration_applies "
                     f"WHERE apply_id = {_lit(apply_id, 'STRING')}").collect()
    if not rows:
        return None
    return {"mode": rows[0]["mode"], "operation": rows[0]["operation"] or "apply", "status": rows[0]["status"],
            "job_run_id": rows[0]["job_run_id"], "workspace_id": rows[0]["workspace_id"]}


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


def selection_fingerprint(params: dict) -> str:
    """Hash of the selection and options an apply run was started with. An execute must match its dry run's hash.

    Order-independent and tolerant of the forms the app and the job see: endpoints are sorted, the secret map is
    re-serialised with sorted keys, flags are compared in lower case, and a missing value counts as empty."""
    fields = {k: _canon(k, params.get(k)) for k in FINGERPRINT_KEYS}
    if fields.get("create_uc_secrets") != "true":
        fields.pop("create_uc_secrets")  # off reads like the runs from before the option, so their hashes still match
    if not fields.get("target_workspace_id"):
        fields.pop("target_workspace_id")  # the hub (blank) reads like runs from before central mode
    return _sha256(json.dumps(fields, sort_keys=True))


def _canon(key: str, value) -> object:
    s = "" if value is None else str(value).strip()
    if key == "endpoints":
        return sorted(e.strip() for e in s.split(",") if e.strip())
    if key == "uc_secret_map" and s:
        try:
            return json.dumps(json.loads(s), sort_keys=True)
        except ValueError:
            return s
    return s.lower() if key in FLAG_KEYS else s


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def _summary_dict(summary) -> dict:
    if isinstance(summary, dict):
        return summary
    try:
        v = json.loads(summary or "{}")
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def rollback_done(status: str | None, summary) -> bool:
    """THE definition of "rolled back" (the store, the job and the app all use this rule).

    A rollback row counts as done when it SUCCEEDED, or when it NEEDS_ATTENTION and every object it kept was kept
    only because another apply run still uses it or it existed before the apply run (summary kept ==
    kept_other_run + kept_preexisting, and no other problems).
    Rollback rows written before kept_other_run existed count as done when NEEDS_ATTENTION, as they always did."""
    if status == "SUCCEEDED":
        return True
    if status != "NEEDS_ATTENTION":
        return False
    s = _summary_dict(summary)
    if "kept_other_run" not in s:  # written before this rule: NEEDS_ATTENTION counted as done
        return True
    # Kept objects that another run uses, or that existed before the apply run, don't keep a rollback from being done.
    return rollback_summary_done(s)


def rollback_blocks(rows: list[dict], w=None, exclude: str | None = None) -> bool:
    """True if a rollback row in rows (apply_id, status, job_run_id, summary) is done or still really running.

    A rollback whose job was killed (RUNNING with its job run ended) doesn't block a new one. exclude is the
    rollback that is asking (its own row)."""
    for r in rows:
        if r.get("apply_id") == exclude:
            continue
        if rollback_done(r.get("status"), r.get("summary")):
            return True
        if r.get("status") == "RUNNING" and (w is None or effective_status(w, "RUNNING", r.get("job_run_id")) == "RUNNING"):
            return True
    return False


def rollback_rows(spark, schema: str, rollback_of: str | None = None) -> list[dict]:
    """Rollback rows (optionally for one execute run): apply_id, rollback_of, status, job_run_id, summary."""
    where = "mode = 'rollback'" + (f" AND rollback_of = {_lit(rollback_of, 'STRING')}" if rollback_of else "")
    rows = spark.sql(f"SELECT apply_id, rollback_of, status, job_run_id, summary FROM {q(schema)}.ug_migration_applies "
                     f"WHERE {where}").collect()
    return [{k: r[k] for k in ("apply_id", "rollback_of", "status", "job_run_id", "summary")} for r in rows]


def rolled_back_ids(rollback: list[dict]) -> set[str]:
    """The execute run ids that a finished rollback row covers."""
    return {r["rollback_of"] for r in rollback if rollback_done(r.get("status"), r.get("summary"))}


def already_rolled_back(spark, schema: str, apply_id: str, w=None, exclude: str | None = None) -> bool:
    """True if a rollback of this execute run is done or still really running (see rollback_blocks)."""
    return rollback_blocks(rollback_rows(spark, schema, apply_id), w, exclude)


def _read_jsonl(path: str) -> list[dict]:
    out = []
    for line in open(path):
        try:
            if line.strip():
                out.append(json.loads(line))
        except ValueError:
            continue  # a torn last line from a killed run
    return out


def pick_run_entries(stored: list[dict], durable_log: str | None) -> list[dict]:
    """The entries of an execute run: its stored result rows, unless they hold no created objects, in which case
    the durable log the run wrote as it went is used (the run was killed before it stored its results)."""
    has_objects = any(e.get("execute") and e.get("action") in OWNED_ACTIONS for e in stored)
    if not has_objects and durable_log and os.path.exists(durable_log):
        return _read_jsonl(durable_log)
    return stored


def apply_log_from_items(spark, schema: str, apply_id: str, path: str, durable_log: str | None = None) -> int:
    """Rebuild an apply log file (for rollback) from a stored apply run.

    Uses the stored result rows; if the execute run was interrupted before it stored them, falls back to the
    durable log the run wrote as it went (durable_log)."""
    rows = spark.sql(f"SELECT payload FROM {q(schema)}.ug_migration_apply_items "
                     f"WHERE apply_id = {_lit(apply_id, 'STRING')} ORDER BY seq").collect()
    entries = pick_run_entries([json.loads(r["payload"]) for r in rows], durable_log)
    n = 0
    with open(path, "w") as f:
        for entry in entries:
            if _is_rollback_entry(entry):
                f.write(json.dumps(entry) + "\n")
                n += 1
    return n


def _is_rollback_entry(e: dict) -> bool:
    """Entries a rollback needs: objects this run created, reused or updated, and the grants it added."""
    if not e.get("execute"):
        return False
    if e.get("action") in OWNED_ACTIONS and e.get("type") in ROLLBACK_TYPES:
        return True
    return e.get("type") == "grant" and e.get("action") == "granted" and bool(e.get("added"))


def protection_runs(spark, schema: str, log_dir: str | None = None) -> list[dict]:
    """Every execute run (stored items, or its durable log in log_dir when the items are missing), and whether a
    rollback of it is done (see rollback_done).

    Feed the result to ug_migration_apply.protection_from_runs to get what a rollback must keep."""
    s = q(schema)
    execs = [r["apply_id"] for r in spark.sql(f"SELECT apply_id FROM {s}.ug_migration_applies "
                                              "WHERE mode = 'execute' AND (operation IS NULL OR operation = 'apply')").collect()]
    stored: dict[str, list[dict]] = {}
    for r in spark.sql(f"SELECT i.apply_id, i.payload FROM {s}.ug_migration_apply_items i "
                       f"JOIN {s}.ug_migration_applies a USING (apply_id) "
                       "WHERE a.mode = 'execute' AND (a.operation IS NULL OR a.operation = 'apply') "
                       "ORDER BY i.apply_id, i.seq").collect():
        stored.setdefault(r["apply_id"], []).append(json.loads(r["payload"]))
    done = rolled_back_ids(rollback_rows(spark, schema))
    return [{"apply_id": aid, "rolled_back": aid in done,
             "entries": pick_run_entries(stored.get(aid, []),
                                         os.path.join(log_dir, f"{aid}.jsonl") if log_dir else None)}
            for aid in execs]


def running_applies(spark, w, schema: str, target_catalog: str, target_schema: str, exclude: str) -> list[str]:
    """Other execute runs for the same target that are still RUNNING (best effort: the check is not atomic)."""
    rows = spark.sql(f"SELECT apply_id, job_run_id, status FROM {q(schema)}.ug_migration_applies "
                     f"WHERE mode = 'execute' AND (operation IS NULL OR operation = 'apply') AND status = 'RUNNING' "
                     f"AND target_catalog = {_lit(target_catalog, 'STRING')} "
                     f"AND target_schema = {_lit(target_schema, 'STRING')} "
                     f"AND apply_id <> {_lit(exclude, 'STRING')}").collect()
    out = []
    for r in rows:
        if w is None or effective_status(w, r["status"], r["job_run_id"]) == "RUNNING":
            out.append(r["apply_id"])
    return out


def is_run_active(spark, w, schema: str, apply_id: str) -> bool:
    """A run the app's store shows as RUNNING whose job run is still going (the checker apply() takes)."""
    row = apply_run(spark, schema, apply_id)
    return bool(row) and effective_status(w, row["status"], row["job_run_id"]) == "RUNNING"


# Options of the other operations (test_call, pause_legacy, enable_tracking, resume_legacy). Stored as the
# fingerprint of those runs; the app compares an execute with its dry run using this same function.
def legacy_fingerprint(params: dict) -> str:
    """Hash of the options a verify-and-cut-over run (any operation but apply) was started with.

    Same rule as selection_fingerprint: an execute must match the dry run it follows. Names are sorted, the API type
    and prompt use their defaults when blank, and the force flag is compared as a boolean."""
    body = json.dumps({
        "operation": str(params.get("operation") or "").strip(),
        "endpoints": _names(params.get("endpoints")),
        "services": _names(params.get("services")),
        "api_type": str(params.get("api_type") or "").strip() or DEFAULT_API_TYPE,
        "prompt": str(params.get("prompt") or "").strip() or DEFAULT_PROMPT,
        "rollback_of": str(params.get("rollback_of") or "").strip(),
        "force": str(params.get("force") or "").strip().lower() in ("true", "1"),
        **({"workspace": str(params.get("target_workspace_id")).strip()}
           if str(params.get("target_workspace_id") or "").strip() else {}),
    }, sort_keys=True)
    return _sha256(body)


def run_fingerprint(params: dict) -> str:
    """The fingerprint a run stores: selection_fingerprint for apply runs, legacy_fingerprint for the other operations."""
    if (params.get("operation") or "apply").strip() in ("", "apply"):
        return selection_fingerprint(params)
    return legacy_fingerprint(params)


def _names(value) -> list[str]:
    return sorted({s.strip() for s in str(value or "").split(",") if s.strip()})


def running_legacy(spark, w, schema: str, exclude: str) -> list[str]:
    """Other write-side cut-over runs (pause, enable tracking, resume) still RUNNING in this results schema.

    Best effort, like running_applies: the check is not atomic, but two runs started together see each other."""
    ops = ", ".join(_lit(op, "STRING") for op in WRITE_LEGACY_OPERATIONS)
    rows = spark.sql(f"SELECT apply_id, job_run_id, status FROM {q(schema)}.ug_migration_applies "
                     f"WHERE status = 'RUNNING' AND operation IN ({ops}) "
                     f"AND apply_id <> {_lit(exclude, 'STRING')}").collect()
    return [r["apply_id"] for r in rows
            if w is None or effective_status(w, r["status"], r["job_run_id"]) == "RUNNING"]


def legacy_run_entries(spark, schema: str, apply_id: str, durable_log: str | None = None) -> list[dict]:
    """The log entries of a run that wasn't apply: its stored result rows, or the durable log it wrote as it went
    when the run was killed before it stored them."""
    rows = spark.sql(f"SELECT payload FROM {q(schema)}.ug_migration_apply_items "
                     f"WHERE apply_id = {_lit(apply_id, 'STRING')} ORDER BY seq").collect()
    stored = [json.loads(r["payload"]) for r in rows]
    if stored or not durable_log or not os.path.exists(durable_log):
        return stored
    return _read_jsonl(durable_log)


# -- Verify helpers (runbook cells 14 and 47). The app runs these with its own query runner. ------------------
# Each builder returns (sql, params). Values are always bound parameters (:name), never interpolated.

_SINCE_RE = re.compile(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?)?")
_SERVICE_RE = re.compile(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_ENDPOINT_RE = re.compile(r"[A-Za-z0-9_\-]+")
MAX_REQUEST_ID_CHARS = 200


def _since(since) -> str:
    s = str(since or "").strip()
    if not _SINCE_RE.fullmatch(s):
        raise ValueError("since must look like 2026-10-01 or 2026-10-01 00:00:00")
    return _utc(s)


# endpoint_name of v1 requests that can't be matched to an endpoint (no served_entities row for their served entity).
UNATTRIBUTED = "(unmatched served entity)"


def legacy_traffic_since(endpoints, since, workspace_id) -> tuple[str, dict]:
    """Traffic per legacy v1 endpoint and requester since a time (README step 4: is traffic stopped?).

    One query, two sources, UNION ALL. 'v1' is system.serving.endpoint_usage joined to served_entities. 'v2' is
    system.ai_gateway.usage rows with no service_type (AI Gateway v2 requests on legacy endpoints). Columns:
    source, endpoint_name, requester, requests, failed (no status, or status 0 or 501), tokens (input plus output
    for v1, total_tokens for v2), last_request (string). Both sources are filtered to workspace_id. v1 requests with no
    served_entities match come back under endpoint_name UNATTRIBUTED (they could be any of this workspace's
    endpoints, so a pause check counts them)."""
    names = _split_names(endpoints)
    if not names:
        raise ValueError("legacy_traffic_since needs at least one endpoint name")
    bad = [n for n in names if not _ENDPOINT_RE.fullmatch(n)]
    if bad:
        raise ValueError(f"bad endpoint name(s) {bad}")
    v1 = {f"v1_{i}": n for i, n in enumerate(names)}
    v2 = {f"v2_{i}": n for i, n in enumerate(names)}
    in_v1 = ", ".join(f":{k}" for k in v1)
    in_v2 = ", ".join(f":{k}" for k in v2)
    params = {"workspace_id": str(workspace_id).strip(), "since": _since(since), **v1, **v2}
    sql = f"""
        SELECT 'v1' AS source, se.endpoint_name AS endpoint_name, eu.requester AS requester,
               count(*) AS requests,
               sum(CASE WHEN eu.status_code IS NULL OR eu.status_code IN (0, 501) THEN 1 ELSE 0 END)
                 AS failed,
               coalesce(sum(coalesce(eu.input_token_count, 0) + coalesce(eu.output_token_count, 0)), 0) AS tokens,
               CAST(max(eu.request_time) AS STRING) AS last_request
        FROM system.serving.endpoint_usage AS eu
        JOIN system.serving.served_entities AS se
          ON eu.served_entity_id = se.served_entity_id
        WHERE eu.workspace_id = :workspace_id
          AND eu.request_time >= CAST(:since AS TIMESTAMP)
          AND se.endpoint_name IN ({in_v1})
        GROUP BY se.endpoint_name, eu.requester
        UNION ALL
        -- v1 requests whose served entity isn't in served_entities can't be tied to an endpoint. They are counted
        -- under UNATTRIBUTED so a pause check fails closed instead of reading them as no traffic.
        SELECT 'v1' AS source, '{UNATTRIBUTED}' AS endpoint_name, eu.requester AS requester,
               count(*) AS requests,
               sum(CASE WHEN eu.status_code IS NULL OR eu.status_code IN (0, 501) THEN 1 ELSE 0 END)
                 AS failed,
               coalesce(sum(coalesce(eu.input_token_count, 0) + coalesce(eu.output_token_count, 0)), 0) AS tokens,
               CAST(max(eu.request_time) AS STRING) AS last_request
        FROM system.serving.endpoint_usage AS eu
        LEFT JOIN system.serving.served_entities AS se
          ON eu.served_entity_id = se.served_entity_id
        WHERE eu.workspace_id = :workspace_id
          AND eu.request_time >= CAST(:since AS TIMESTAMP)
          AND se.served_entity_id IS NULL
        GROUP BY eu.requester
        UNION ALL
        SELECT 'v2' AS source, endpoint_name, requester,
               count(*) AS requests,
               sum(CASE WHEN status_code IS NULL OR status_code IN (0, 501) THEN 1 ELSE 0 END) AS failed,
               coalesce(sum(total_tokens), 0) AS tokens,
               CAST(max(event_time) AS STRING) AS last_request
        FROM system.ai_gateway.usage
        WHERE workspace_id = :workspace_id
          AND service_type IS NULL
          AND endpoint_name IN ({in_v2})
          AND event_time >= CAST(:since AS TIMESTAMP)
        GROUP BY endpoint_name, requester
        ORDER BY endpoint_name, source, requester
    """
    return sql, params


def ug_usage_summary(service, since) -> tuple[str, dict]:
    """Model Service usage since a time, per service, workspace, requester, API type and destination (runbook cell 47).

    service is a three-part name, or blank for every visible Model Service. Only service_type = 'MODEL_SERVICE' rows
    are counted (legacy v2 rows have no Model Service). Columns: service_name, workspace_id, requester, api_type,
    destination_model, requests (distinct request_id), invocations, total_tokens, average_latency_ms,
    p95_latency_ms, error_invocations (status >= 400), last_request (string)."""
    params = {"since": _since(since)}
    service_filter = ""
    svc = str(service or "").strip()
    if svc:
        if not _SERVICE_RE.fullmatch(svc):
            raise ValueError("service must be a three-part catalog.schema.name, or blank for all")
        params["service"] = svc
        service_filter = "AND service_name = :service"
    sql = f"""
        SELECT
          service_name, workspace_id, requester, api_type, destination_model,
          count(DISTINCT request_id) AS requests,
          count(*) AS invocations,
          coalesce(sum(total_tokens), 0) AS total_tokens,
          round(avg(latency_ms), 1) AS average_latency_ms,
          percentile_approx(latency_ms, 0.95) AS p95_latency_ms,
          sum(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS error_invocations,
          CAST(max(event_time) AS STRING) AS last_request
        FROM system.ai_gateway.usage
        WHERE event_time >= CAST(:since AS TIMESTAMP)
          AND service_type = 'MODEL_SERVICE'
          {service_filter}
        GROUP BY service_name, workspace_id, requester, api_type, destination_model
        ORDER BY total_tokens DESC, requests DESC
    """
    return sql, params


def ug_request_lookup(request_id) -> tuple[str, dict]:
    """Usage rows for one request id (runbook cell 14). A request can have several rows, one per routed invocation.

    Usage can take 20 to 30 minutes to appear after the call, so an empty result is not a failure."""
    rid = str(request_id or "").strip()
    if not rid or len(rid) > MAX_REQUEST_ID_CHARS or any(c.isspace() for c in rid):
        raise ValueError("request_id must be a non-empty id without spaces")
    sql = """
        SELECT event_time, invocation_id, service_name, destination_model, status_code,
               input_tokens, output_tokens, total_tokens, latency_ms
        FROM system.ai_gateway.usage
        WHERE request_id = :request_id
        ORDER BY event_time DESC
    """
    return sql, {"request_id": rid}


def dry_run_used(schema: str, dry_run_id: str) -> tuple[str, dict]:
    """The execute runs that already followed a dry run (column apply_id). Each dry run is good for one execute, so
    a non-empty result refuses the next one. Rows written before dry_run_id existed have it NULL and match nothing."""
    return (f"SELECT apply_id FROM {q(schema)}.ug_migration_applies "
            "WHERE dry_run_id = :dry_run_id AND mode = 'execute' ORDER BY started_at LIMIT 1",
            {"dry_run_id": str(dry_run_id or "")})


def run_built(spark, built: tuple[str, dict]) -> list:
    """Run one of the builders above on a Spark session (named parameters). The app uses its own runner instead."""
    sql, params = built
    return spark.sql(sql, args=params).collect()


def _split_names(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = str(value or "").split(",")
    return sorted({p.strip() for p in parts if p.strip()})


now = _now


def test_call_candidates(spark, schema: str, scan_run_id: str) -> tuple[set[str], dict[str, str]]:
    """What a test call may target (the job's check; the app applies the same rule): the target services of the
    scan's plan, and model services that apply executes created or found, minus those a rollback deleted since,
    lower-cased name -> the workspace the run acted on (blank = the hub)."""
    targets: set[str] = set()
    if scan_run_id:
        if not re.fullmatch(r"[0-9a-f-]{36}", scan_run_id):
            raise ValueError(f"bad scan id {scan_run_id!r}")
        for r in spark.sql(f"SELECT get_json_object(payload, '$.target_service') AS t FROM {q(schema)}.ug_migration_scan_items "
                           f"WHERE run_id = '{scan_run_id}' AND item_type = 'plan'").collect():
            if r["t"]:
                targets.add(str(r["t"]).lower())
    created: dict[str, str] = {}
    rows = spark.sql(f"""
        SELECT a.workspace_id, get_json_object(i.payload, '$.name') AS name, get_json_object(i.payload, '$.action') AS action
        FROM {q(schema)}.ug_migration_apply_items i JOIN {q(schema)}.ug_migration_applies a ON a.apply_id = i.apply_id
        WHERE a.mode IN ('execute', 'rollback') AND (a.operation IS NULL OR a.operation = 'apply')
          AND get_json_object(i.payload, '$.type') = 'model_service'
          AND get_json_object(i.payload, '$.action') IN ('created', 'exists', 'deleted')
        ORDER BY a.started_at, i.seq""").collect()
    for r in rows:
        name = str(r["name"] or "").lower()
        if not name:
            continue
        if r["action"] == "deleted":
            created.pop(name, None)
        else:
            created[name] = str(r["workspace_id"] or "")
    return targets, created
