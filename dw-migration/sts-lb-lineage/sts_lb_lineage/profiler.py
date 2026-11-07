"""Read table volumes from a Lakebridge Profiler extract (DuckDB file).

The Profiler's table-level layout is not documented and differs by source, so this scans the
extract for a table that has a table-name column plus a row-count and/or size column. It opens
the file read-only and prints what it used, so you can check the match.
"""

from pathlib import Path

NAME = ("table_name", "tablename", "object_name", "name", "table")
SCHEMA = (
    "table_schema",
    "schema_name",
    "schemaname",
    "schema",
    "database_name",
    "owner",
)
ROWS = (
    "row_count",
    "rowcount",
    "num_rows",
    "rows",
    "record_count",
    "row_cnt",
    "table_rows",
)
BYTES = (
    "size_bytes",
    "bytes",
    "total_bytes",
    "table_size_bytes",
    "size_in_bytes",
    "data_size_bytes",
    "table_bytes",
)


def _pick(cols: list[str], options: tuple) -> str | None:
    low = {c.lower(): c for c in cols}
    return next((low[o] for o in options if o in low), None)


def load_profiler(path: Path) -> tuple[dict[str, dict], str]:
    """Returns (volumes keyed like --volumes, description of the source table)."""
    try:
        import duckdb
    except ImportError as e:  # optional extra
        raise SystemExit(
            "--profiler needs duckdb: install with the [profiler] extra"
        ) from e

    con = duckdb.connect(str(path), read_only=True)
    try:
        rows = con.execute(
            "select table_schema, table_name, column_name from information_schema.columns "
            "where table_schema not in ('information_schema', 'pg_catalog')"
        ).fetchall()
        by_table: dict[tuple, list[str]] = {}
        for sch, tbl, col in rows:
            by_table.setdefault((sch, tbl), []).append(col)
        best = None
        for (sch, tbl), cols in by_table.items():
            name, rows_c, bytes_c = (
                _pick(cols, NAME),
                _pick(cols, ROWS),
                _pick(cols, BYTES),
            )
            if name and (rows_c or bytes_c):
                score = (rows_c is not None) + (bytes_c is not None)
                if not best or score > best[0]:
                    best = (score, sch, tbl, name, _pick(cols, SCHEMA), rows_c, bytes_c)
        if not best:
            raise SystemExit(
                f"{path}: no table with a table-name column plus row-count or size columns found"
            )
        _, sch, tbl, name_c, schema_c, rows_c, bytes_c = best
        q = lambda c: '"' + c.replace('"', '""') + '"'
        select = [
            q(name_c),
            q(schema_c) if schema_c else "NULL",
            q(rows_c) if rows_c else "NULL",
            q(bytes_c) if bytes_c else "NULL",
        ]
        data = con.execute(
            f"select {', '.join(select)} from {q(sch)}.{q(tbl)}"
        ).fetchall()
    finally:
        con.close()
    out: dict[str, dict] = {}
    for name, schema, n_rows, n_bytes in data:
        if not name:
            continue
        key = f"{schema}.{name}" if schema and "." not in str(name) else str(name)
        vol = {
            k: int(v)
            for k, v in (("rows", n_rows), ("bytes", n_bytes))
            if v is not None
        }
        if vol:
            out[key.lower()] = vol
    used = f"{sch}.{tbl} (name={name_c}, schema={schema_c}, rows={rows_c}, bytes={bytes_c})"
    return out, used
