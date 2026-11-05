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
    from .core import safe_writer

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
    links = [
        {"external_metadata": names[n["id"]], "table": n["uc"]["target"]}
        for n in d["nodes"]
        if n["id"] in names and n.get("uc") and not n["uc"]["target"].startswith("<")
    ]
    return {
        "external_metadata": metadata,
        "external_lineage": rels,
        "table_links": links,
    }


def _client(profile: str):
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(profile=profile)


def _em(name: str):
    from databricks.sdk.service import catalog as c

    return c.ExternalLineageObject(
        external_metadata=c.ExternalLineageExternalMetadata(name=name)
    )


def _tbl(name: str):
    from databricks.sdk.service import catalog as c

    return c.ExternalLineageObject(table=c.ExternalLineageTable(name=name))


def existing_names(w, prefix: str) -> set[str]:
    return {
        m.name
        for m in w.external_metadata.list_external_metadata()
        if m.name and m.name.startswith(f"{prefix}__")
    }


def push(
    p: dict,
    profile: str,
    assume_yes: bool = False,
    link: bool = False,
    prefix: str = "legacy",
):
    """Create the payload in a workspace. Shows a plan (new vs existing) first, only creates,
    and skips objects that already exist, so reruns are safe. With link=True, also links each
    legacy table to its suggested UC table when that table exists."""
    n_meta, n_rel = (
        len(p["external_metadata"]),
        len(p["external_lineage"]) + (len(p["table_links"]) if link else 0),
    )
    if n_meta > MAX_METADATA or n_rel > MAX_RELATIONSHIPS:
        sys.exit(
            f"Payload exceeds UC limits ({n_meta}/{MAX_METADATA} metadata, {n_rel}/{MAX_RELATIONSHIPS} "
            "relationships). Narrow it with --focus or split the reports."
        )
    from databricks.sdk.errors import AlreadyExists, ResourceAlreadyExists
    from databricks.sdk.service import catalog as c

    w = _client(profile)
    have = existing_names(w, prefix)
    new_meta = sum(1 for m in p["external_metadata"] if m["name"] not in have)
    links = []
    if link:
        for t in p["table_links"]:
            if w.tables.exists(t["table"]).table_exists:
                links.append(t)
    print(f"Workspace {w.config.host} (profile {profile}). Plan:")
    print(f"  external metadata: {new_meta} new, {n_meta - new_meta} already there")
    print(
        f"  relationships: up to {len(p['external_lineage'])} between legacy tables (existing ones are skipped)"
    )
    if link:
        print(
            f"  links to UC tables: {len(links)} of {len(p['table_links'])} suggested targets exist"
        )
    if (
        not assume_yes
        and input("Create them? Type 'yes' to continue: ").strip().lower() != "yes"
    ):
        sys.exit("Cancelled.")
    made = skipped = 0
    for m in p["external_metadata"]:
        if m["name"] in have:
            skipped += 1
            continue
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
    rels = [
        (
            r["source"]["external_metadata"]["name"],
            _em(r["source"]["external_metadata"]["name"]),
            _em(r["target"]["external_metadata"]["name"]),
            r["properties"],
        )
        for r in p["external_lineage"]
    ]
    rels += [
        (
            t["external_metadata"],
            _em(t["external_metadata"]),
            _tbl(t["table"]),
            {"kind": "migrated_to"},
        )
        for t in links
    ]
    made = skipped = 0
    for _, src, dst, props in rels:
        try:
            w.external_lineage.create_external_lineage_relationship(
                c.CreateRequestExternalLineage(source=src, target=dst, properties=props)
            )
            made += 1
        except (AlreadyExists, ResourceAlreadyExists):
            skipped += 1
    print(f"Relationships: {made} created, {skipped} already existed.")
    return {"metadata_created": new_meta, "links": len(links)}


def remove(profile: str, prefix: str, assume_yes: bool = False) -> int:
    """Delete the external metadata objects named <prefix>__* and their relationships.
    Only names with the prefix are touched; UC tables are never deleted."""
    if not prefix or prefix != ident(prefix):
        sys.exit("--uc-remove needs a plain --uc-prefix (letters, digits, underscores)")
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service import catalog as c

    w = _client(profile)
    names = sorted(existing_names(w, prefix))
    print(
        f"Workspace {w.config.host} (profile {profile}): {len(names)} external metadata objects named {prefix}__*"
    )
    if not names:
        return 0
    for n in names[:20]:
        print(f"  {n}")
    if len(names) > 20:
        print(f"  ... and {len(names) - 20} more")
    print(
        "  Objects with this prefix created by other users or tools are included. Use a unique --uc-prefix."
    )
    if (
        not assume_yes
        and input("Delete them and their relationships? Type 'yes': ").strip().lower()
        != "yes"
    ):
        sys.exit("Cancelled.")
    rels = 0
    for name in names:
        for direction in (c.LineageDirection.DOWNSTREAM, c.LineageDirection.UPSTREAM):
            for info in w.external_lineage.list_external_lineage_relationships(
                object_info=_em(name), lineage_direction=direction
            ):
                if info.external_metadata_info:
                    other = _em(info.external_metadata_info.name)
                elif info.table_info:
                    t = info.table_info
                    other = _tbl(f"{t.catalog_name}.{t.schema_name}.{t.name}")
                else:
                    continue
                src, dst = (
                    (_em(name), other)
                    if direction == c.LineageDirection.DOWNSTREAM
                    else (other, _em(name))
                )
                try:
                    w.external_lineage.delete_external_lineage_relationship(
                        c.DeleteRequestExternalLineage(source=src, target=dst)
                    )
                    rels += 1
                except NotFound:
                    pass
    for name in names:
        try:
            w.external_metadata.delete_external_metadata(name)
        except NotFound:
            pass
    print(f"Deleted {rels} relationships and {len(names)} external metadata objects.")
    return len(names)


def system_type_for(platform: str | None, override: str | None) -> str:
    if override:
        return override.upper()
    return SYSTEM_TYPE.get((platform or "").lower(), "OTHER")


def write_payload(p: dict, out: Path) -> Path:
    path = out / "uc_external_lineage.json"
    path.write_text(json.dumps(p, indent=2))
    return path
