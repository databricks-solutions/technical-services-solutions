"""Unity Catalog helpers for sts-lb-lineage: target mapping, volumes, external lineage payload/push."""

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

LAYER = {"source": "bronze", "intermediate": "silver", "terminal": "gold"}
# analyzer platform name -> UC external metadata system_type (SDK catalog.SystemType)
SYSTEM_TYPE = {
    "oracle": "ORACLE",
    "teradata": "TERADATA",
    "ms sql server": "MICROSOFT_SQL_SERVER",
    "snowflake": "SNOWFLAKE",
    "redshift": "AMAZON_REDSHIFT",
    "synapse": "AZURE_SYNAPSE",
}
MAX_METADATA = 10_000  # per metastore, UC external lineage limits
MAX_RELATIONSHIPS = 100_000


def ident(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_") or "_"


def suggest(name: str, role: str, catalog: str, pattern: str) -> dict | None:
    """Suggested UC target for one legacy table. Temp tables and orphans get none."""
    if name[:1] in "@#" or role not in LAYER:
        return None
    schema, _, table = name.rpartition(".")
    fields = {
        "catalog": catalog or "<catalog>",
        "layer": LAYER[role],
        "schema": ident(schema.split(".")[-1]) if schema else "default",
        "table": ident(table),
    }
    return {"layer": LAYER[role], "target": pattern.format(**fields)}


def load_volumes(path: Path) -> dict[str, dict]:
    """CSV with a table (or name) column plus rows and/or bytes. Keys are lower-cased names."""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            name = row.get("table") or row.get("name")
            if not name:
                continue
            vol = {k: int(float(row[k])) for k in ("rows", "bytes") if row.get(k)}
            if vol:
                out[name.lower()] = vol
    return out


def enrich(
    d: dict,
    catalog: str = "",
    pattern: str = "{catalog}.{schema}.{table}",
    volumes: dict | None = None,
) -> dict:
    """Add `uc` and `volume` to table nodes and roll volumes up to processes."""
    volumes = volumes or {}
    by_short: dict[str, list[str]] = {}
    for k in volumes:
        by_short.setdefault(k.rsplit(".", 1)[-1], []).append(k)
    matched = 0
    for n in d["nodes"]:
        if n["kind"] != "table":
            continue
        uc = suggest(n["name"], n.get("role", ""), catalog, pattern)
        if uc:
            n["uc"] = uc
        key = n["name"].lower()
        bare = key.rsplit(".", 1)[-1]
        # fall back to the bare name only when one side has no schema, never across schemas
        if key not in volumes and "." in key and bare in volumes:
            key = bare
        elif key not in volumes and "." not in key and len(by_short.get(bare, [])) == 1:
            key = by_short[bare][0]
        if key in volumes:
            n["volume"] = volumes[key]
            matched += 1
    if volumes:
        vol = {n["id"]: n["volume"] for n in d["nodes"] if "volume" in n}
        for p in d["insights"]["processes"]:
            p["volume"] = {
                k: sum(vol[i].get(k, 0) for i in p["objects"] if i in vol)
                for k in ("rows", "bytes")
            }
        d["insights"]["summary"]["volumes"] = {
            "provided": len(volumes),
            "matched": matched,
        }
    return d


def write_mapping(d: dict, out: Path):
    from sts_lb_lineage import safe_writer

    with open(out / "uc_mapping.csv", "w", newline="") as f:
        w = safe_writer(f)
        w.writerow(
            [
                "source_table",
                "role",
                "process",
                "layer",
                "suggested_target",
                "rows",
                "bytes",
            ]
        )
        for n in d["nodes"]:
            if n["kind"] == "table":
                uc, vol = n.get("uc") or {}, n.get("volume") or {}
                w.writerow(
                    [
                        n["name"],
                        n.get("role", ""),
                        n.get("process", ""),
                        uc.get("layer", ""),
                        uc.get("target", ""),
                        vol.get("rows", ""),
                        vol.get("bytes", ""),
                    ]
                )


def payload(d: dict, system_type: str = "OTHER", prefix: str = "legacy") -> dict:
    """UC external lineage objects for the legacy estate: one external metadata object per
    table, one relationship per table-to-table data edge (jobs are kept as edge properties)."""
    names: dict[str, str] = {}
    used: set[str] = set()
    for n in d["nodes"]:
        if n["kind"] != "table":
            continue
        base = f"{ident(prefix)}__{ident(n['name'])}"[:240]
        name = (
            base
            if base not in used
            else f"{base}_{hashlib.sha1(n['name'].encode()).hexdigest()[:6]}"
        )
        used.add(name)
        names[n["id"]] = name
    nodes = {n["id"]: n for n in d["nodes"]}
    metadata = [
        {
            "name": names[i],
            "system_type": system_type,
            "entity_type": "table",
            "description": f"Legacy table {nodes[i]['name']} (sts-lb-lineage). Role: {nodes[i].get('role')}. "
            f"Process: {nodes[i].get('process')}.",
            "properties": {
                "legacy_name": nodes[i]["name"],
                "role": str(nodes[i].get("role", "")),
                "process": str(nodes[i].get("process", ""))[:500],
                **(
                    {"suggested_target": nodes[i]["uc"]["target"]}
                    if nodes[i].get("uc")
                    else {}
                ),
            },
        }
        for i in names
    ]
    rels = [
        {
            "source": {"external_metadata": {"name": names[e["from"]]}},
            "target": {"external_metadata": {"name": names[e["to"]]}},
            "properties": {
                "via": ", ".join(e["via"][:5])[:500],
                "grain": e["grain"],
                "tech": e["tech"],
            },
        }
        for e in d["edges"]
        if e["kind"] == "data" and e["from"] in names and e["to"] in names
    ]
    return {"external_metadata": metadata, "external_lineage": rels}


def push(p: dict, profile: str, assume_yes: bool = False):
    """Create the payload in a workspace. Existing objects are skipped, so reruns are safe."""
    n_meta, n_rel = len(p["external_metadata"]), len(p["external_lineage"])
    if n_meta > MAX_METADATA or n_rel > MAX_RELATIONSHIPS:
        sys.exit(
            f"Payload exceeds UC limits ({n_meta}/{MAX_METADATA} metadata, {n_rel}/{MAX_RELATIONSHIPS} "
            "relationships). Narrow it with --focus or split the reports."
        )
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import AlreadyExists, ResourceAlreadyExists
    from databricks.sdk.service import catalog as c

    w = WorkspaceClient(profile=profile)
    print(
        f"Workspace {w.config.host} (profile {profile}): {n_meta} external metadata, {n_rel} relationships."
    )
    if (
        not assume_yes
        and input("Create them? Type 'yes' to continue: ").strip().lower() != "yes"
    ):
        sys.exit("Cancelled.")
    made = skipped = 0
    for m in p["external_metadata"]:
        try:
            w.external_metadata.create_external_metadata(
                c.ExternalMetadata(
                    name=m["name"],
                    system_type=c.SystemType(m["system_type"]),
                    entity_type=m["entity_type"],
                    description=m["description"],
                    properties=m["properties"],
                )
            )
            made += 1
        except (AlreadyExists, ResourceAlreadyExists):
            skipped += 1
    print(f"External metadata: {made} created, {skipped} already existed.")
    made = skipped = 0
    for r in p["external_lineage"]:
        try:
            w.external_lineage.create_external_lineage_relationship(
                c.CreateRequestExternalLineage(
                    source=c.ExternalLineageObject(
                        external_metadata=c.ExternalLineageExternalMetadata(
                            name=r["source"]["external_metadata"]["name"]
                        )
                    ),
                    target=c.ExternalLineageObject(
                        external_metadata=c.ExternalLineageExternalMetadata(
                            name=r["target"]["external_metadata"]["name"]
                        )
                    ),
                    properties=r["properties"],
                )
            )
            made += 1
        except (AlreadyExists, ResourceAlreadyExists):
            skipped += 1
    print(f"External lineage: {made} created, {skipped} already existed.")


def system_type_for(platform: str | None, override: str | None) -> str:
    if override:
        return override.upper()
    return SYSTEM_TYPE.get((platform or "").lower(), "OTHER")


def write_payload(p: dict, out: Path) -> Path:
    path = out / "uc_external_lineage.json"
    path.write_text(json.dumps(p, indent=2))
    return path
