#!/usr/bin/env python3
"""Export Snowflake DDL (and optional workload SQL) for Lakebridge Analyzer.

Run this on a laptop or jump host with network access to Snowflake — not in Databricks.
Hand the output folder to Lakebridge Analyzer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
from collections import defaultdict

SYSTEM_DATABASES = {"SNOWFLAKE", "SNOWFLAKE_SAMPLE_DATA"}
SYSTEM_SCHEMAS = {"INFORMATION_SCHEMA"}
SHOW_PAGE_SIZE = 10000

# Snowflake has no classic triggers; streams/tasks/pipes cover event-driven objects.
OBJECT_FOLDERS = (
    "tables",
    "views",
    "materialized_views",
    "functions",
    "procedures",
    "sequences",
    "file_formats",
    "streams",
    "tasks",
    "pipes",
    "masking_policies",
    "row_access_policies",
    "tags",
)

OBJECT_EXPORTS = [
    ("SHOW TABLES", "TABLE", "tables"),
    ("SHOW VIEWS", "VIEW", "views"),
    ("SHOW MATERIALIZED VIEWS", "MATERIALIZED VIEW", "materialized_views"),
    ("SHOW SEQUENCES", "SEQUENCE", "sequences"),
    ("SHOW FILE FORMATS", "FILE FORMAT", "file_formats"),
    ("SHOW STREAMS", "STREAM", "streams"),
    ("SHOW TASKS", "TASK", "tasks"),
    ("SHOW PIPES", "PIPE", "pipes"),
    ("SHOW MASKING POLICIES", "POLICY", "masking_policies"),
    ("SHOW ROW ACCESS POLICIES", "POLICY", "row_access_policies"),
    ("SHOW TAGS", "TAG", "tags"),
]

DDL_QUERY_TYPES = (
    "CREATE_TABLE",
    "CREATE_VIEW",
    "CREATE_FUNCTION",
    "CREATE_PROCEDURE",
    "CREATE_TASK",
    "CREATE_PIPE",
    "CREATE_STREAM",
    "CREATE_TABLE_AS_SELECT",
    "ALTER_TABLE",
    "ALTER_SESSION",
    "DROP",
    "GRANT",
    "REVOKE",
    "USE",
    "DESCRIBE",
    "SHOW",
    "UNKNOWN",
)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def safe_filename(s: str, max_len: int = 120) -> str:
    raw = s or "unnamed"
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", raw)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._") or "unnamed"
    if cleaned == raw.replace(" ", "_") and len(cleaned) <= max_len:
        return cleaned
    suffix = hashlib.md5(raw.encode()).hexdigest()[:8]
    if len(cleaned) > max_len - 9:
        cleaned = cleaned[: max_len - 9]
    return f"{cleaned}_{suffix}"


def db_dir(out_base: pathlib.Path, db: str) -> pathlib.Path:
    return out_base / safe_filename(db)


def object_dir(out_base: pathlib.Path, db: str, object_type: str) -> pathlib.Path:
    return db_dir(out_base, db) / object_type


def ensure_db_folders(out_base: pathlib.Path, db: str) -> None:
    root = db_dir(out_base, db)
    for folder in OBJECT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)


def write_sql(out_dir: pathlib.Path, filename: str, sql_text: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_text(sql_text or "", encoding="utf-8")


def run_show(cur, sql: str) -> tuple[list[str], list[tuple]]:
    cur.execute(sql)
    cols = [d[0].lower() for d in cur.description]
    return cols, cur.fetchall()


def run_show_paginated(cur, show_sql: str) -> tuple[list[str], list[tuple]]:
    cols: list[str] = []
    rows: list[tuple] = []
    last_name = None
    while True:
        sql = f"{show_sql} LIMIT {SHOW_PAGE_SIZE}"
        if last_name:
            sql += f" FROM '{last_name.replace(chr(39), chr(39) * 2)}'"
        page_cols, page = run_show(cur, sql)
        if not cols:
            cols = page_cols
        if not page:
            break
        rows.extend(page)
        if len(page) < SHOW_PAGE_SIZE:
            break
        last_name = dict(zip(page_cols, page[-1])).get("name")
        if not last_name:
            break
    return cols, rows


def safe_get_ddl(cur, obj_type: str, fq_name: str) -> str | None:
    try:
        safe_id = fq_name.replace("'", "''")
        cur.execute(f"SELECT GET_DDL('{obj_type}', '{safe_id}', true)")
        result = cur.fetchone()
        return result[0] if result and result[0] else None
    except Exception as e:
        print(f"[WARN] GET_DDL failed for {obj_type} {fq_name}: {e}")
        return None


def connect():
    account = env("SNOWFLAKE_ACCOUNT")
    user = env("SNOWFLAKE_USER")
    role = env("SNOWFLAKE_ROLE")
    warehouse = env("SNOWFLAKE_WAREHOUSE")
    missing = [n for n, v in [
        ("SNOWFLAKE_ACCOUNT", account),
        ("SNOWFLAKE_USER", user),
        ("SNOWFLAKE_ROLE", role),
        ("SNOWFLAKE_WAREHOUSE", warehouse),
    ] if not v]
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    kwargs = {
        "user": user,
        "account": account,
        "role": role,
        "warehouse": warehouse,
        "session_parameters": {"QUERY_TAG": "lakebridge_export"},
    }
    authenticator = env("SNOWFLAKE_AUTHENTICATOR", "snowflake")
    if authenticator and authenticator != "snowflake":
        kwargs["authenticator"] = authenticator
    else:
        password = env("SNOWFLAKE_PASSWORD")
        if not password:
            sys.exit("Set SNOWFLAKE_PASSWORD or SNOWFLAKE_AUTHENTICATOR=externalbrowser")
        kwargs["password"] = password
    try:
        import snowflake.connector
    except ImportError:
        sys.exit("Install dependencies first: pip install -r requirements.txt")
    return snowflake.connector.connect(**kwargs)


def list_databases(cur, allowlist: list[str] | None) -> list[str]:
    if allowlist:
        return allowlist
    cols, rows = run_show(cur, "SHOW DATABASES")
    names = []
    for row in rows:
        name = dict(zip(cols, row)).get("name", "")
        if name.upper() not in SYSTEM_DATABASES:
            names.append(name)
    return names


def list_schemas(cur, db: str) -> list[str]:
    cols, rows = run_show(cur, f'SHOW SCHEMAS IN "{db}"')
    names = []
    for row in rows:
        name = dict(zip(cols, row)).get("name", "")
        if name.upper() not in SYSTEM_SCHEMAS:
            names.append(name)
    return names


def export_simple_objects(cur, out_base: pathlib.Path, db: str, schema: str) -> dict[str, list[str]]:
    extracted: dict[str, list[str]] = defaultdict(list)
    for show_cmd, ddl_type, subfolder in OBJECT_EXPORTS:
        try:
            cols, rows = run_show_paginated(cur, f'{show_cmd} IN "{db}"."{schema}"')
        except Exception as e:
            print(f"[WARN] {show_cmd} in {db}.{schema} failed: {e}")
            continue
        out_dir = object_dir(out_base, db, subfolder)
        for row in rows:
            name = dict(zip(cols, row)).get("name", "")
            if not name:
                continue
            fq = f'"{db}"."{schema}"."{name}"'
            ddl = safe_get_ddl(cur, ddl_type, fq)
            if ddl:
                fn = f"{safe_filename(schema)}.{safe_filename(name)}.sql"
                write_sql(out_dir, fn, ddl)
                extracted[ddl_type].append(name)
    return extracted


def signature_for_get_ddl(arguments: str) -> str:
    if not arguments or not arguments.strip():
        return "()"
    no_return = re.sub(r"\s+RETURN\s+.*$", "", arguments.strip(), flags=re.IGNORECASE)
    if re.match(r"^[^(]*\(\s*\)\s*$", no_return):
        return "()"
    match = re.match(r"^[^(]*\((.+)\)\s*$", no_return)
    return f"({match.group(1).strip()})" if match else f"({no_return})"


def export_callables(cur, out_base: pathlib.Path, db: str, schema: str, obj_type: str, subfolder: str) -> dict[str, list[str]]:
    extracted: dict[str, list[str]] = defaultdict(list)
    show_cmd = f'SHOW USER {obj_type}S IN SCHEMA "{db}"."{schema}"'
    try:
        cols, rows = run_show_paginated(cur, show_cmd)
    except Exception as e:
        print(f"[WARN] {show_cmd} failed: {e}")
        return extracted

    out_dir = object_dir(out_base, db, subfolder)
    for row in rows:
        r = dict(zip(cols, row))
        name = r.get("name", "")
        if not name or name.startswith("SYSTEM$"):
            continue
        sig = signature_for_get_ddl(r.get("arguments", "") or "")
        fq_sig = f'"{db}"."{schema}"."{name}"{sig}'
        ddl = safe_get_ddl(cur, obj_type, fq_sig)
        if ddl:
            sig_part = safe_filename(sig.replace(" ", "").replace(",", "_"))
            fn = f"{safe_filename(schema)}.{safe_filename(name)}_{sig_part}.sql"
            write_sql(out_dir, fn, ddl)
            extracted[obj_type].append(name)
    return extracted


def split_statements(query_text: str) -> list[str]:
    parts = [p.strip() for p in (query_text or "").split(";")]
    return [p + ";" for p in parts if p]


def export_queries(cur, out_base: pathlib.Path, databases: list[str], days: int) -> int:

    excluded = ", ".join(f"'{t}'" for t in DDL_QUERY_TYPES)
    where = (
        f"start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()) "
        f"AND query_text IS NOT NULL "
        f"AND query_type NOT IN ({excluded})"
    )
    if databases:
        db_filter = " OR ".join(f"database_name = '{db.replace(chr(39), chr(39) * 2)}'" for db in databases)
        where += f" AND ({db_filter})"

    sql = f"""
        SELECT ANY_VALUE(query_text) AS query_text,
               ANY_VALUE(database_name) AS database_name,
               ANY_VALUE(schema_name) AS schema_name,
               MIN(start_time) AS first_seen
        FROM snowflake.account_usage.query_history
        WHERE {where}
        GROUP BY query_parameterized_hash
        ORDER BY first_seen
    """
    try:
        cur.execute(sql)
    except Exception as e:
        print(f"[WARN] Query history export failed: {e}")
        print("[WARN] Needs IMPORTED PRIVILEGES on DATABASE SNOWFLAKE. DDL export is still valid.")
        return 0

    rows = cur.fetchall()
    print(f"[INFO] Exporting {len(rows)} unique queries...")
    written = 0
    for i, (query_text, db, sch, ts) in enumerate(rows, start=1):
        if not query_text:
            continue
        db, sch = db or "NA", sch or "NA"
        ts_str = ts.strftime("%Y%m%d_%H%M%S") if ts else f"no_ts_{i}"
        out_dir = object_dir(out_base, db, "queries")
        for j, stmt in enumerate(split_statements(query_text), start=1):
            fn = f"{ts_str}_{safe_filename(sch)}_{i}_{j}.sql"
            write_sql(out_dir, fn, stmt)
            written += 1
    print(f"[INFO] Wrote {written} unique workload SQL file(s).")
    return written


def parse_args():
    p = argparse.ArgumentParser(
        description="Export Snowflake metadata for Databricks Lakebridge Analyzer."
    )
    p.add_argument("--output", default="snowflake_input", help="Output directory")
    p.add_argument(
        "--databases",
        default=env("SNOWFLAKE_DATABASES", ""),
        help="Comma-separated database allowlist. Default: all non-system databases.",
    )
    p.add_argument(
        "--include-workloads",
        action="store_true",
        help="Also export deduplicated ACCOUNT_USAGE query history (needs extra grants).",
    )
    p.add_argument("--days", type=int, default=90, help="Query-history lookback if --include-workloads")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_base = pathlib.Path(args.output)
    if out_base.exists():
        print(f"[INFO] Writing into existing folder {out_base} (files with the same name will be overwritten).")
    out_base.mkdir(parents=True, exist_ok=True)

    allowlist = [d.strip() for d in (args.databases or "").split(",") if d.strip()]
    conn = connect()
    cur = conn.cursor()
    total: dict[str, list[str]] = defaultdict(list)
    workload_count = 0

    try:
        databases = list_databases(cur, allowlist or None)
        print(f"[INFO] Databases: {databases}")
        for db in databases:
            ensure_db_folders(out_base, db)
            try:
                schemas = list_schemas(cur, db)
            except Exception as e:
                print(f"[WARN] Could not list schemas in {db}: {e}")
                continue
            for schema in schemas:
                print(f"[INFO] Exporting {db}.{schema} ...")
                for result in (
                    export_simple_objects(cur, out_base, db, schema),
                    export_callables(cur, out_base, db, schema, "FUNCTION", "functions"),
                    export_callables(cur, out_base, db, schema, "PROCEDURE", "procedures"),
                ):
                    for key, names in result.items():
                        total[key].extend(names)
        if args.include_workloads:
            workload_count = export_queries(cur, out_base, databases, args.days)
    finally:
        cur.close()
        conn.close()

    summary = {t: len(v) for t, v in sorted(total.items())}
    summary["objects_total"] = sum(summary.values())
    summary["workload_queries"] = workload_count
    (out_base / "export_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n[SUMMARY] {summary['objects_total']} objects extracted:")
    for t, n in summary.items():
        if t not in {"objects_total", "workload_queries"}:
            print(f"   {t}: {n}")
    if args.include_workloads:
        print(f"   workload queries: {workload_count}")
    print(f"[INFO] Output ready for Lakebridge Analyzer: {out_base.resolve()}")


if __name__ == "__main__":
    main()
