#!/usr/bin/env python3
"""ingest.py — normalise ANY estate input into one `inventory.json`.

The inventory is the only thing `design.py` reads, so new sources never touch the design logic:
  • Raw files   .twbx/.tdsx (Tableau), .pbit/.pbix (Power BI) — parsed structurally, never data.
  • Live MCP / API   the AGENT pulls reports, measures and datasources from a Tableau / Power BI
                MCP connection and writes `<name>.inventory.json` (same schema, see
                references/inventory-schema.md). ingest.py merges every such file it finds.
  • Documents   .md .txt .csv .pdf .docx .pptx .html … are catalogued under `documents`; the agent
                reads them and writes the business terms it finds to `glossary.yaml`
                (term / definition / synonyms / domain_hint) which ingest.py merges as well.

Usage:  ingest.py <input dir or files...> -o output/inventory.json [--account "Acme"]
Deterministic: same inputs ⇒ byte-identical inventory (no timestamps, sorted keys).
"""
import argparse
import collections
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "adapters"))
from smlib import slug, read_yaml, read_json, write_json  # noqa: E402

DOC_EXT = (".md", ".txt", ".csv", ".pdf", ".docx", ".pptx", ".html", ".htm", ".xlsx", ".json", ".yaml", ".yml")
RAW_EXT = (".twbx", ".twb", ".tdsx", ".pbit", ".pbix")


def walk(paths):
    out = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            for root, _d, files in os.walk(p):
                if os.path.sep + "output" in root + os.path.sep:  # never re-ingest our own output
                    continue
                out += [os.path.join(root, f) for f in files]
        elif os.path.exists(p):
            out.append(p)
    return sorted(out)


def tableau_reports(files):
    import parse_twbx as pt
    from parse_common import classify
    twb = [f for f in files if f.lower().endswith((".twbx", ".twb"))]
    reports = []
    for f in twb:
        for member, root in pt.xml_members(f):
            nm = member[:-4] if member.lower().endswith(".twb") else os.path.splitext(os.path.basename(f))[0]
            wb = pt.parse_workbook(nm, root)
            fact = pt.group_key(wb["tables"])
            cal = next((t for t in wb["tables"] if classify(t) == "calendar"), None)
            reports.append(dict(
                id="tableau-" + slug(nm), name=nm, tool="tableau", kind="workbook",
                fact_tables=[fact] if fact else [], tables=sorted(wb["tables"]), calendar=cal,
                measures=[dict(name=c, formula=fm) for c, fm in wb["calcs"]],
                pages=wb["n_dashboards"], visuals=wb["n_worksheets"], params=wb["params"],
                text_pct=round(wb["text_pct"], 3), source=wb["source"], thin=False, note=""))
    return reports


def powerbi_reports(files):
    import parse_pbit as pp
    out = []
    for f in [f for f in files if f.lower().endswith((".pbit", ".pbix"))]:
        try:
            r = pp.parse_pbit(f)
        except Exception as e:  # one unreadable report must not sink the stack
            print(f"  WARN skipped {os.path.basename(f)} — {type(e).__name__}: {e}", file=sys.stderr)
            continue
        fact = r.get("fact_phys") or r.get("fact") or r.get("dataset")
        out.append(dict(
            id="powerbi-" + slug(r["name"]), name=r["name"], tool="powerbi", kind=r["kind"],
            fact_tables=[fact] if fact else [], tables=[], calendar=r.get("calendar"),
            measures=[dict(name=n, formula=d) for (n, d, _h) in r["measures"]],
            pages=r["n_pages"], visuals=r["n_visuals"], params=r["params"], text_pct=0.0,
            source=r["source"], thin=bool(r.get("thin")), note=r.get("note") or ""))
    return out


def merge_extra(files, inv):
    for f in files:
        b = os.path.basename(f).lower()
        if b.endswith(".inventory.json") or b.endswith(".inventory.yaml"):
            d = read_json(f) if b.endswith(".json") else read_yaml(f)
            for k in ("reports", "documents", "glossary_terms", "physical_tables"):
                inv[k] += (d or {}).get(k, [])
        elif b in ("glossary.yaml", "glossary.yml", "glossary.json"):
            d = read_json(f) if b.endswith(".json") else read_yaml(f)
            inv["glossary_terms"] += (d or {}).get("terms", d if isinstance(d, list) else [])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("-o", "--out", default="output/inventory.json")
    ap.add_argument("--account", default="TODO — customer name")
    a = ap.parse_args()

    files = walk(a.paths)
    inv = dict(schema=1, account=a.account, reports=[], documents=[], glossary_terms=[], physical_tables=[])
    inv["reports"] += tableau_reports(files)
    inv["reports"] += powerbi_reports(files)
    merge_extra(files, inv)
    for f in files:
        if f.lower().endswith(DOC_EXT) and not f.lower().endswith((".inventory.json", ".inventory.yaml")) \
                and os.path.basename(f).lower() not in ("glossary.yaml", "glossary.yml", "glossary.json"):
            inv["documents"].append(dict(path=os.path.relpath(f), kind=os.path.splitext(f)[1].lstrip(".")))

    # de-dup + stable order (idempotent output)
    seen, reps = set(), []
    for r in sorted(inv["reports"], key=lambda r: r["id"]):
        if r["id"] not in seen:
            seen.add(r["id"]); reps.append(r)
    inv["reports"] = reps
    inv["documents"] = sorted(inv["documents"], key=lambda d: d["path"])
    inv["glossary_terms"] = sorted(inv["glossary_terms"], key=lambda t: str(t.get("term", "")).lower())

    write_json(a.out, inv)
    nm = sum(len(r["measures"]) for r in reps)
    thin = [r["name"] for r in reps if r.get("thin")]
    print(f"inventory: {len(reps)} reports ({collections.Counter(r['tool'] for r in reps).most_common()}), "
          f"{nm} measures, {len(inv['documents'])} documents, {len(inv['glossary_terms'])} glossary terms → {a.out}")
    for t in thin:
        print(f"  ⚠ thin report (no readable model): {t} — its semantics are missing until exported", file=sys.stderr)
    if not reps and not inv["glossary_terms"]:
        print("  ⚠ nothing parseable found — for a live MCP source, write <name>.inventory.json "
              "(references/inventory-schema.md) and re-run.", file=sys.stderr)


if __name__ == "__main__":
    main()
