"""Column-level lineage from embedded ETL SQL (analyzer `sqlStatements[].sql`), using sqlglot.

Handles INSERT INTO t [(cols)] SELECT ... and CREATE TABLE t AS SELECT ...; table aliases are
resolved. Statements that do not parse, or other statement types, are skipped and counted.
"""

DIALECT = {
    "ORACLE": "oracle",
    "TERADATA": "teradata",
    "SNOWFLAKE": "snowflake",
    "SAS": None,
}


def _table_name(t) -> str:
    parts = [
        p
        for p in (t.args.get("catalog"), t.args.get("db"), t.args.get("this"))
        if p is not None
    ]
    return ".".join(p.name for p in parts)


def column_edges(statements: list[dict]) -> tuple[list[dict], dict]:
    """Returns (edges, stats). Each edge: {from: 'tbl.col', to: 'tbl.col', via: job}."""
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as e:  # optional extra
        raise SystemExit(
            "--columns needs sqlglot: install with the [columns] extra"
        ) from e

    edges: dict[tuple, dict] = {}
    stats = {"statements": len(statements), "parsed": 0, "skipped": 0}
    for st in statements:
        try:
            tree = sqlglot.parse_one(st["sql"], read=DIALECT.get(st.get("tech")))
        except Exception:  # noqa: BLE001 - analyzer SQL is often vendor-specific; skip it
            stats["skipped"] += 1
            continue
        if isinstance(tree, exp.Insert):
            target, select = tree.this, tree.expression
            cols = (
                [c.name for c in target.expressions]
                if isinstance(target, exp.Schema)
                else []
            )
            target = target.this if isinstance(target, exp.Schema) else target
        elif isinstance(tree, exp.Create) and isinstance(tree.expression, exp.Select):
            target, select, cols = tree.this, tree.expression, []
            target = target.this if isinstance(target, exp.Schema) else target
        else:
            stats["skipped"] += 1
            continue
        if not isinstance(target, exp.Table) or not isinstance(select, exp.Select):
            stats["skipped"] += 1
            continue
        tgt = _table_name(target)
        aliases = {}
        for t in select.find_all(exp.Table):
            aliases[(t.alias_or_name or "").lower()] = _table_name(t)
            aliases[_table_name(t).lower()] = _table_name(t)
        sources = {_table_name(t) for t in select.find_all(exp.Table)}
        for i, proj in enumerate(select.expressions):
            out = cols[i] if i < len(cols) else proj.alias_or_name
            if not out or out == "*":
                continue
            for col in proj.find_all(exp.Column):
                src_tbl = (
                    aliases.get((col.table or "").lower())
                    if col.table
                    else (next(iter(sources)) if len(sources) == 1 else None)
                )
                if not src_tbl:
                    continue
                key = (f"{src_tbl}.{col.name}".lower(), f"{tgt}.{out}".lower())
                e = edges.setdefault(
                    key,
                    {
                        "from": f"{src_tbl}.{col.name}",
                        "to": f"{tgt}.{out}",
                        "via": set(),
                    },
                )
                e["via"].add(st["job"])
        stats["parsed"] += 1
    return [{**e, "via": sorted(e["via"])} for e in edges.values()], stats
