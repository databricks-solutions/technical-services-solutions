"""Export the lineage and insights to Delta tables in a Unity Catalog schema.

Rows are written as JSON-lines files to a UC volume (Files API) and loaded with read_files, so
object names never become SQL text. Only the validated catalog and schema names appear in SQL.
"""

import io
import json
import re
import sys
import time

VOLUME = "sts_lb_lineage_files"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def rows(d: dict) -> dict[str, list[dict]]:
    proc_of_prog = {
        p: pr["name"] for pr in d["insights"]["processes"] for p in pr["programs"]
    }
    nodes = {n["id"]: n for n in d["nodes"]}
    return {
        "nodes": [
            {
                "id": n["id"],
                "name": n["name"],
                "kind": n["kind"],
                "process": n.get("process"),
                "role": n.get("role"),
                "tags": n.get("tags", []),
                "uc_target": (n.get("uc") or {}).get("target"),
                "uc_layer": (n.get("uc") or {}).get("layer"),
                "rows": (n.get("volume") or {}).get("rows"),
                "bytes": (n.get("volume") or {}).get("bytes"),
            }
            for n in d["nodes"]
        ],
        "edges": [
            {
                "source": nodes[e["from"]]["name"],
                "target": nodes[e["to"]]["name"],
                "source_id": e["from"],
                "target_id": e["to"],
                "kind": e["kind"],
                "via": e["via"],
                "grain": e["grain"],
                "tech": e["tech"],
            }
            for e in d["edges"]
        ],
        "processes": [
            {
                "name": p["name"],
                "tech": p["tech"],
                "programs": len(p["programs"]),
                "objects": len(p["objects"]),
                "max_complexity": p["maxComplexity"],
                "in_cycle": p["cycle"] is not None,
                "depends_on": p["upstream"],
                "feeds": p["downstream"],
            }
            for p in d["insights"]["processes"]
        ],
        "shared_tables": [
            {
                "id": h["id"],
                "name": nodes[h["id"]]["name"],
                "process_count": h["processCount"],
                "writers": h["writers"],
                "readers": h["readers"],
            }
            for h in d["insights"]["hubs"]
        ],
        "programs": [
            {
                "name": p["name"],
                "tech": p["tech"],
                "type": p.get("type"),
                "complexity": p.get("complexity"),
                "reads": len(p["reads"]),
                "writes": len(p["writes"]),
                "process": proc_of_prog.get(p["name"]),
            }
            for p in d["programs"]
        ],
        "columns": [
            {"source": c["from"], "target": c["to"], "via": c["via"]}
            for c in d.get("columns", [])
        ],
        "summary": [
            {
                "insights_json": json.dumps(
                    {
                        k: v
                        for k, v in d["insights"].items()
                        if k in ("summary", "statistics", "trust")
                    }
                )
            }
        ],
    }


def _sql(w, warehouse: str, statement: str):
    from databricks.sdk.service.sql import StatementState

    r = w.statement_execution.execute_statement(
        warehouse_id=warehouse, statement=statement, wait_timeout="50s"
    )
    while r.status and r.status.state in (
        StatementState.PENDING,
        StatementState.RUNNING,
    ):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        err = r.status.error.message if r.status and r.status.error else r.status
        raise SystemExit(f"SQL failed: {err}")


def export(
    d: dict, target: str, profile: str, warehouse: str, assume_yes: bool = False
) -> list[str]:
    parts = target.split(".")
    if len(parts) != 2 or not all(IDENT.match(p) for p in parts):
        raise SystemExit(
            "--uc-export needs CATALOG.SCHEMA with letters, digits, and underscores only"
        )
    catalog, schema = parts
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=profile)
    data = {k: v for k, v in rows(d).items() if v}
    tables = [f"{catalog}.{schema}.lineage_{k}" for k in data]
    print(
        f"Workspace {w.config.host} (profile {profile}): create or replace {len(tables)} tables in {catalog}.{schema}:"
    )
    print("  " + ", ".join(t.split(".")[-1] for t in tables))
    if not assume_yes and input("Continue? Type 'yes': ").strip().lower() != "yes":
        sys.exit("Cancelled.")
    _sql(w, warehouse, f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
    _sql(w, warehouse, f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{VOLUME}")
    for name, records in data.items():
        path = f"/Volumes/{catalog}/{schema}/{VOLUME}/{name}.json"
        body = "\n".join(json.dumps(r, default=str) for r in records).encode()
        w.files.upload(path, io.BytesIO(body), overwrite=True)
        _sql(
            w,
            warehouse,
            f"CREATE OR REPLACE TABLE {catalog}.{schema}.lineage_{name} AS "
            f"SELECT * FROM read_files('{path}', format => 'json')",
        )
        print(f"  lineage_{name}: {len(records)} rows")
    return tables
