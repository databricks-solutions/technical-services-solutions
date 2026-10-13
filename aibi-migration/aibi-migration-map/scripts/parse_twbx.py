#!/usr/bin/env python3
"""
parse_twbx.py — a PRIMARY input for the migration map: raw Tableau files in, starter
`mapping.yaml` out. It reads `.twbx` workbooks (and `.tdsx` shared datasources) directly
from a folder (e.g. a scanned Volume of exported files) — no separate extraction step needed.

For each workbook it reads the packaged `.twb` XML and extracts *what the workbook does*:
worksheets, dashboards, upstream tables (from custom SQL + physical relations), calculated
fields, parameters, and mark types. It then:

  1. CLUSTERS workbooks on their shared **fact table** (the skill's "group on shared fact
     tables, not folders" methodology — done automatically, since raw files expose the SQL).
  2. ROUTES each workbook to a Databricks asset kind via the purpose-only rule in route.py
     (Lakeview dashboard / Genie space / App / SQL Alert). No complexity/effort/compat scoring.
  3. SEEDS each group's **Metric View** from the real calculated fields it found — candidate
     metrics, the shared calendar/time dimension, and detected **drift** (the same metric
     defined with different formulas across workbooks — the business case for the layer).

Output is a starter mapping.yaml. A human then curates names / consolidation / MV concepts and
runs render.py. Curation is where the judgment lives; this just gets the extraction out of the way.

Usage:
  python3 scripts/parse_twbx.py <path ...> -o mapping.yaml [--account NAME] [--title TITLE]
    <path> may be directories (scanned for *.twbx / *.tdsx) or individual files.
"""
import os, sys, re, glob, zipfile, argparse, collections
import xml.etree.ElementTree as ET
try:
    import yaml  # noqa: F401  (used by route.write_mapping)
except ImportError:
    sys.exit("Needs pyyaml.  pip install pyyaml")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route  # noqa: E402  routing rule + mapping builder live here
from parse_common import (  # noqa: E402  shared parse helpers (also used by parse_pbit.py)
    TABLE_RE, FCT_STRICT_RE, classify, seed_from_calcs, suggest_semantics)


# ---- archive reading -----------------------------------------------------
def xml_members(path):
    """Yield (member_name, root_element) for each .twb/.tds inside a .twbx/.tdsx (or a bare .twb/.tds)."""
    if path.lower().endswith((".twb", ".tds")):
        yield os.path.basename(path), ET.parse(path).getroot()
        return
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.lower().endswith((".twb", ".tds")):
                yield os.path.basename(n), ET.fromstring(z.read(n))


def collect_tables(root):
    """Referenced upstream tables: custom-SQL FROM/JOIN targets + physical <relation table=...>."""
    toks = collections.Counter()
    for r in root.iter("relation"):
        if r.get("type") == "text" and r.text:
            for m in TABLE_RE.findall(r.text):
                toks[m.lower()] += 1
        elif r.get("type") == "table" and r.get("table"):
            t = r.get("table").strip("[]").replace("].[", ".").lower()
            toks[t] += 1
    return toks


def collect_connections(root):
    """Distinct upstream systems (redshift/athena/published/excel/...) — 'extract' if only local."""
    classes = set()
    for c in root.iter("connection"):
        cls = (c.get("class") or "").lower()
        if not cls or cls in ("federated",):
            continue
        if cls in ("hyper", "textscan", "excel-direct"):
            classes.add("extract")
        elif cls == "sqlproxy":
            classes.add("published-datasource")
        else:
            classes.add(cls)
    return classes


def collect_calcs(root):
    """[(caption, formula)] for every calculated field with a real Tableau formula."""
    out = []
    for col in root.iter("column"):
        calc = col.find("calculation")
        if calc is not None and calc.get("class") == "tableau" and calc.get("formula"):
            cap = col.get("caption") or col.get("name", "").strip("[]")
            out.append((cap, calc.get("formula")))
    return out


def count_params(root):
    caps = set()
    for ds in root.findall("./datasources/datasource"):
        if (ds.get("name") == "Parameters") or (ds.get("caption") == "Parameters"):
            for c in ds.findall("./column"):
                caps.add(c.get("caption") or c.get("name"))
    for col in root.iter("column"):
        if col.get("param-domain-type"):
            caps.add(col.get("caption") or col.get("name"))
    return len(caps)


def text_pct(root):
    marks = collections.Counter(m.get("class") for m in root.iter("mark"))
    total = sum(marks.values())
    if not total:
        return 0.0
    # 'Text' marks are explicit crosstabs; everything else is a visual mark.
    return marks.get("Text", 0) / total


def parse_workbook(name, root):
    worksheets = [w.get("name") for w in root.iter("worksheet")]
    dashboards = [d.get("name") for d in root.iter("dashboard")]
    tables = collect_tables(root)
    conns = collect_connections(root)
    calcs = collect_calcs(root)
    real_ds = [ds for ds in root.findall("./datasources/datasource")
               if ds.get("name") not in ("Parameters",) and ds.get("name") != "" ]
    return dict(
        name=name, worksheets=worksheets, dashboards=dashboards,
        n_worksheets=len(worksheets), n_dashboards=len(dashboards),
        tables=tables, conns=conns, calcs=calcs,
        datasources=max(len(conns), 1),
        params=count_params(root), n_calcs=len(calcs),
        text_pct=text_pct(root),
        source=", ".join(sorted(conns)) or "extract",
    )


def group_key(tables):
    """Pick the fact table this workbook is built on. Calendar/noise never win."""
    ranked = []
    for tok, cnt in tables.items():
        kind = classify(tok)
        if kind in ("calendar", "noise"):
            continue
        # priority: true fact (_fct) > other fact (_data/_rev) > other table > dim ; then frequency
        if kind == "fact":
            prio = 0 if FCT_STRICT_RE.search(tok) else 1
        else:
            prio = {"other": 2, "dim": 3}[kind]
        ranked.append((prio, -cnt, tok))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


# ---- main ----------------------------------------------------------------
def discover(paths):
    twbx, tdsx = [], []
    for p in paths:
        if os.path.isdir(p):
            twbx += sorted(glob.glob(os.path.join(p, "**", "*.twbx"), recursive=True))
            twbx += sorted(glob.glob(os.path.join(p, "**", "*.twb"), recursive=True))
            tdsx += sorted(glob.glob(os.path.join(p, "**", "*.tdsx"), recursive=True))
            tdsx += sorted(glob.glob(os.path.join(p, "**", "*.tds"), recursive=True))
        elif p.lower().endswith((".twbx", ".twb")):
            twbx.append(p)
        elif p.lower().endswith((".tdsx", ".tds")):
            tdsx.append(p)
    return sorted(set(twbx)), sorted(set(tdsx))


def humanize(tok):
    return tok  # fact-table token is honest + precise; curator renames to a business subject area


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="directories and/or .twbx/.tdsx files")
    ap.add_argument("-o", "--out", default="mapping.yaml")
    ap.add_argument("--account", default="TODO — customer name")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    twbx, tdsx = discover(args.paths)
    if not twbx:
        sys.exit("No .twbx/.twb workbooks found in: " + ", ".join(args.paths))

    parsed = []
    for f in twbx:
        for member, root in xml_members(f):
            nm = member[:-4] if member.lower().endswith((".twb",)) else os.path.splitext(os.path.basename(f))[0]
            parsed.append(parse_workbook(nm, root))

    # shared datasources (.tdsx): name -> dominant schema, for the MV "shared logic" note
    shared_ds = []
    for f in tdsx:
        for member, root in xml_members(f):
            nm = member[:-4]
            tabs = collect_tables(root)
            schemas = collections.Counter(t.split(".")[0] for t in tabs if classify(t) not in ("noise",))
            shared_ds.append(dict(name=nm, schema=(schemas.most_common(1)[0][0] if schemas else None)))

    # assign a group (fact table) to each workbook
    for wb in parsed:
        gk = group_key(wb["tables"])
        if gk is None:
            # no upstream fact — fall back to the source system so it still lands somewhere
            gk = next(iter(sorted(wb["conns"])), "ungrouped")
        wb["group"] = humanize(gk)
        wb["_group_key"] = gk

    # ---- seed Metric Views per group from the real calc fields ----
    seeds = {}
    groups = collections.defaultdict(list)
    for wb in parsed:
        groups[wb["group"]].append(wb)

    for glabel, wbs in groups.items():
        # candidate metrics + drift — shared with parse_pbit via parse_common.seed_from_calcs
        items = [(cap, formula, wb["name"]) for wb in wbs for cap, formula in wb["calcs"]]
        metric_caps, drift = seed_from_calcs(items, require_agg=True)
        # shared calendar/time dimension?
        cal = None
        for wb in wbs:
            for tok in wb["tables"]:
                if classify(tok) == "calendar":
                    cal = tok
                    break
            if cal:
                break
        # shared published datasources whose schema matches this fact's schema
        gschema = glabel.split(".")[0]
        shared = [f"Published datasource: {d['name']}" for d in shared_ds if d["schema"] and d["schema"] == gschema]

        title, purpose, grain = suggest_semantics(glabel, metric_caps, phys=glabel)
        seeds[glabel] = dict(
            title=title,
            core_source=glabel,
            purpose=purpose,
            grain=grain,
            time_dimension=(f"{cal} (calendar — conformed, shared across the estate)" if cal else "TODO — the date/time dimension"),
            metrics=(metric_caps[:12] or ["TODO"]),
            drift=drift[:12],
            shared=shared,
        )

    # normalized rows for the builder
    rows = [dict(name=wb["name"], group=wb["group"], worksheets=wb["n_worksheets"],
                 datasources=wb["datasources"], source=wb["source"], text_pct=wb["text_pct"],
                 params=wb["params"], n_calcs=wb["n_calcs"], purpose="", drivers="")
            for wb in parsed]

    mapping = route.build_mapping(rows, account=args.account, title=args.title, seeds=seeds, source_tool="Tableau")
    mapping["meta"]["source_note"] = (f"Parsed directly from {len(twbx)} Tableau workbook(s)"
                                      + (f" and {len(tdsx)} shared datasource(s)" if tdsx else "")
                                      + " by the aibi-migration-map skill (parse_twbx.py).")
    route.write_mapping(mapping, args.out)

    route.summarize(mapping, f"raw parse of {len(twbx)} workbook(s)")
    ndrift = sum(len(mv.get("drift", [])) for mv in mapping["metric_views"].values())
    print(f"Seeded {len(mapping['metric_views'])} metric views from calc fields, {ndrift} drift signals detected.")
    print(f"Wrote {args.out} — curate it, then: python3 scripts/render.py {args.out} -o report.html")


if __name__ == "__main__":
    main()
