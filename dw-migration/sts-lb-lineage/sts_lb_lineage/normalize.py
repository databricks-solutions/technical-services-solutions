"""Name normalization: resolve unqualified names with a schema search path and fold ETL
instance names (SQ_<table>, <table>_1) into their base table. Both are opt-in."""

import re


def merge(lin, alias: dict[str, str]) -> int:
    """Rewrite node ids old -> new in nodes, edges, and programs. Returns merged count."""
    alias = {
        a: b for a, b in alias.items() if a != b and b in lin.nodes and a in lin.nodes
    }
    if not alias:
        return 0
    for old, new in alias.items():
        lin.nodes[new]["tags"] |= lin.nodes[old]["tags"] | {"merged"}
        del lin.nodes[old]
    edges = {}
    for (a, b, kind), e in lin.edges.items():
        a, b = alias.get(a, a), alias.get(b, b)
        if a == b:
            continue
        cur = edges.get((a, b, kind))
        if cur:
            cur["via"] |= e["via"]
            if e["grain"] == "statement":
                cur["grain"] = "statement"
        else:
            edges[(a, b, kind)] = {**e, "from": a, "to": b, "via": set(e["via"])}
    lin.edges = edges
    for p in lin.programs.values():
        p["reads"] = {alias.get(x, x) for x in p["reads"]}
        p["writes"] = {alias.get(x, x) for x in p["writes"]}
    return len(alias)


def search_path_aliases(lin, schemas: list[str]) -> dict[str, str]:
    """Unqualified table X -> schema.X when exactly one schema on the path has it."""
    tables = {
        n["name"].lower(): nid for nid, n in lin.nodes.items() if n["kind"] == "table"
    }
    out = {}
    for nid, n in lin.nodes.items():
        name = n["name"]
        if n["kind"] != "table" or "." in name or name[:1] in "@#":
            continue
        hits = [
            tables[f"{s.lower()}.{name.lower()}"]
            for s in schemas
            if f"{s.lower()}.{name.lower()}" in tables
        ]
        if len(hits) == 1:
            out[nid] = hits[0]
    return out


_INSTANCE = [
    re.compile(r"^(?:SQ|LKP)_(.+)$", re.IGNORECASE),
    re.compile(r"^(.+?)_?\d+$"),
]


def instance_aliases(lin) -> dict[str, str]:
    """ETL instance names: SQ_<base> (source qualifier), LKP_<base> (lookup) and <base>_1 / <base>1 -> <base>."""
    tables = {
        n["name"].lower(): nid for nid, n in lin.nodes.items() if n["kind"] == "table"
    }
    out = {}
    for nid, n in lin.nodes.items():
        if n["kind"] != "table":
            continue
        for rx in _INSTANCE:
            m = rx.match(n["name"])
            if m and m.group(1).lower() in tables and tables[m.group(1).lower()] != nid:
                out[nid] = tables[m.group(1).lower()]
                break
    return out


_CTE = re.compile(
    r"(?:\bWITH\b(?:\s+RECURSIVE)?|,)\s*([A-Za-z_][\w$#]*)\s*(?:\([^()]*\))?\s+AS\s*\(",
    re.IGNORECASE,
)


def cte_names(texts) -> set[str]:
    """Names defined as common table expressions (WITH x AS (...), y AS (...)) in SQL text."""
    return {m.group(1).lower() for t in texts for m in _CTE.finditer(t)}


def source_texts(folder, max_bytes: int = 200_000_000):
    """Text of the scanned source files (read-only), for --run. Stops after max_bytes."""
    from pathlib import Path

    total = 0
    for f in sorted(Path(folder).rglob("*")):
        if not f.is_file() or f.stat().st_size > 20_000_000:
            continue
        total += f.stat().st_size
        if total > max_bytes:
            return
        yield f.read_text(encoding="utf-8", errors="ignore")


def flag_ctes(lin, texts) -> dict[str, int]:
    """Tag tables that are CTE names (found in SQL text) as "cte", and unqualified, never-written
    tables that are read only together with schema-qualified tables as "maybe-cte" (a CTE or an
    alias the Lakebridge Analyzer did not resolve)."""
    ctes = cte_names(texts)
    written = {t for p in lin.programs.values() for t in p["writes"]}
    found = maybe = 0
    for nid, n in lin.nodes.items():
        name = n["name"]
        if n["kind"] != "table" or "." in name or name[:1] in "@#":
            continue
        if name.lower() in ctes:
            n["tags"].add("cte")
            found += 1
            continue
        if nid in written:
            continue
        others = {
            t
            for p in lin.programs.values()
            if nid in p["reads"]
            for t in p["reads"]
            if t != nid
        }
        named = [lin.nodes[t]["name"] for t in others if t in lin.nodes]
        if any("." in x for x in named) and all(
            "." in x or x[:1] in "@#" for x in named
        ):
            n["tags"].add("maybe-cte")
            maybe += 1
    return {"cteTables": found, "possibleCteTables": maybe}
