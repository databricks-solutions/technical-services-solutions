#!/usr/bin/env python3
"""
parse_pbit.py — the Power BI counterpart to parse_twbx.py: raw `.pbit` template files in,
starter `mapping.yaml` out. Same idea, Power BI vocabulary.

A `.pbit` is a zip. This reads the `DataModelSchema` (the tabular model — tables, relationships,
and **DAX measures**) and the `Report/definition` pages, and extracts *what the report/model does*:

  1. CLUSTERS reports on their shared **fact table** — identified from the model's relationship
     graph (the hub every dimension points at), mapped to its upstream physical table via the
     Power Query (M) partition source. This is the "group on shared fact tables" methodology.
  2. ROUTES each report via the purpose-only rule in route.py (Lakeview dashboard / Genie / App /
     SQL Alert). No complexity/effort/compatibility scoring.
  3. SEEDS each group's **Metric View** from the real **DAX measures** — candidate metrics, the
     shared date/time dimension, and detected **drift** (the same measure defined with different
     DAX across report variants — the business case for a single semantic layer).

A single `.pbit` = one report/model = one "workbook" row (its pages ≈ dashboards). Near-duplicate
variants of one model therefore cluster together, and their measure drift surfaces automatically.

Output is a starter mapping.yaml; curate it, then run render.py — identical to the Tableau flow.

Usage:
  python3 scripts/parse_pbit.py <path ...> -o mapping.yaml [--account NAME] [--title TITLE]
    <path> may be directories (scanned for *.pbit) or individual .pbit files.
"""
import os, sys, re, glob, json, zipfile, argparse, collections

try:
    import yaml  # noqa: F401  (used by route.write_mapping)
except ImportError:
    sys.exit("Needs pyyaml.  pip install pyyaml")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route  # noqa: E402
from parse_common import classify, seed_from_calcs, suggest_semantics  # noqa: E402

# M connector -> friendly source system label
CONNECTOR = [
    (re.compile(r"Databricks\.\w+"), "databricks"),
    (re.compile(r"Snowflake\.\w+"), "snowflake"),
    (re.compile(r"AmazonRedshift\.\w+"), "redshift"),
    (re.compile(r"GoogleBigQuery\.\w+|BigQuery\."), "bigquery"),
    (re.compile(r"Sql\.Databases?"), "sqlserver"),
    (re.compile(r"Oracle\.\w+"), "oracle"),
    (re.compile(r"PostgreSQL\.\w+"), "postgres"),
    (re.compile(r"Excel\.Workbook|Csv\.Document"), "file"),
    (re.compile(r"Web\.\w+|Json\.\w+"), "web/api"),
]
# the upstream table a model table is bound to: ... Name = "X", Kind = "Table" ...
M_TABLE_RE = re.compile(r'Name\s*=\s*"([^"]+)"\s*,\s*Kind\s*=\s*"Table"')
# native SQL query embedded in M: Value.NativeQuery(_, "select ... from cat.sch.tbl ...")
M_NATIVE_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w]*\.[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)", re.I)


def load_json(z, member):
    try:
        raw = z.read(member)
    except KeyError:
        return None  # member absent (e.g. a thin/live-connection report has no DataModelSchema)
    for enc in ("utf-16-le", "utf-16", "utf-8-sig", "utf-8"):
        try:
            s = raw.decode(enc)
            if s and s[0] == "﻿":
                s = s[1:]
            return json.loads(s)
        except Exception:
            continue
    return None


def parse_connections(z):
    """A thin report (no embedded model) declares its upstream dataset/source in `Connections`.
    Return (source_label, dataset_name) so it still routes and clusters with the model it uses."""
    j = load_json(z, "Connections")
    for c in (j or {}).get("Connections", []):
        cs = c.get("ConnectionString") or c.get("connectionString") or ""
        low = cs.lower()
        m = re.search(r"initial catalog=([^;]+)", cs, re.I)
        name = (m.group(1).strip() if m else c.get("Name")) or None
        if any(k in low for k in ("pbiazure", "powerbi://", "analysis services", "asazure", "pbidedicated")):
            return "power-bi-dataset (live)", name
        if "databricks" in low or "sparksql" in low:
            return "databricks", name
        if "sql" in low:
            return "sqlserver", name
        if cs or c.get("ConnectionType"):
            return (c.get("ConnectionType") or "live-connection"), name
    return None, None


def legacy_layout_counts(z):
    """Pages/visuals for the legacy single-blob `Report/Layout` (older + thin reports)."""
    lay = load_json(z, "Report/Layout")
    if not lay:
        return 0, 0
    secs = lay.get("sections", [])
    return len(secs), sum(len(s.get("visualContainers", [])) for s in secs)


def _text(x):
    """Model expressions/measures store DAX/M as a string or a list of lines."""
    if isinstance(x, list):
        return "\n".join(x)
    return x or ""


def m_source_of(table):
    """Return (upstream_table, connector_label) for a model table's partition M source."""
    for p in table.get("partitions", []):
        src = p.get("source", {})
        expr = _text(src.get("expression"))
        if not expr:
            continue
        conn = next((lbl for rx, lbl in CONNECTOR if rx.search(expr)), None)
        tbl = None
        m = M_TABLE_RE.search(expr)
        if m:
            tbl = m.group(1)
        else:
            n = M_NATIVE_RE.search(expr)
            if n:
                tbl = n.group(1)
        if conn or tbl:
            return tbl, (conn or "unknown")
    return None, None


def measures_of(model):
    """[(measure_name, dax, home_table)] across every table in the model."""
    out = []
    for t in model.get("tables", []):
        for meas in t.get("measures", []):
            out.append((meas.get("name", ""), _text(meas.get("expression")), t.get("name")))
    return out


def n_calcs_of(model):
    n = 0
    for t in model.get("tables", []):
        n += len(t.get("measures", []))
        n += sum(1 for c in t.get("columns", []) if c.get("type") == "calculated" or c.get("expression"))
    return n


def n_params_of(model):
    """Power BI parameters: model expressions flagged as parameters, or what-if parameter tables."""
    caps = set()
    for e in model.get("expressions", []):
        anns = {a.get("name"): a.get("value") for a in e.get("annotations", [])}
        if e.get("kind") == "m" and anns.get("PBI_ResultType") == "Parameter":
            caps.add(e.get("name"))
    for t in model.get("tables", []):
        anns = {a.get("name"): a.get("value") for a in t.get("annotations", [])}
        if anns.get("PBI_Id") and "Parameter" in str(anns.get("PBI_ResultType", "")):
            caps.add(t.get("name"))
    return len(caps)


def fact_table(model, upstream):
    """The fact = the relationship hub (highest-degree non-dimension model table)."""
    rel = model.get("relationships", [])
    deg = collections.Counter()
    for r in rel:
        deg[r.get("fromTable")] += 1
        deg[r.get("toTable")] += 1
    # measure-only tables: a calculated table whose only job is to hold measures
    measure_only = set()
    for t in model.get("tables", []):
        if t.get("measures") and all(p.get("source", {}).get("type") == "calculated" for p in t.get("partitions", [{}])):
            measure_only.add(t.get("name"))
    cand = []
    for name, d in deg.items():
        if name in measure_only:
            continue
        if classify(name) in ("dim", "calendar"):  # dimension by name
            continue
        cand.append((d, name))
    if cand:
        cand.sort(reverse=True)
        return cand[0][1]
    # fallback: a model table with an upstream table that isn't a dimension
    for name, (tbl, _c) in upstream.items():
        if tbl and classify(name) not in ("dim", "calendar"):
            return name
    return None


def parse_pbit(path):
    z = zipfile.ZipFile(path)
    dm = load_json(z, "DataModelSchema") or {}
    model = dm.get("model", {})
    tables = model.get("tables", [])
    # upstream physical table + connector per model table
    upstream = {t.get("name"): m_source_of(t) for t in tables}
    connectors = {c for (_t, c) in upstream.values() if c and c != "unknown"}
    n_src = len({t for (t, _c) in upstream.values() if t})  # distinct upstream tables ≈ #datasources

    # report pages / visuals — PBIR (Report/definition/pages/*/) or legacy blob (Report/Layout)
    pages = [n for n in z.namelist() if re.search(r"pages/[^/]+/page\.json$", n)]
    visuals = [n for n in z.namelist() if re.search(r"/visuals/[^/]+/visual\.json$", n)]
    n_pages, n_visuals = len(pages), len(visuals)
    if n_pages == 0:  # legacy Report/Layout (older reports + thin/live-connection reports)
        n_pages, n_visuals = legacy_layout_counts(z)

    # THIN: no machine-readable model (a live-connection report, OR a .pbix whose model is the
    # binary `DataModel` blob we can't read). Don't crash — degrade to routing the report by its
    # source, and WARN the user what to export to recover the measures / Metric View.
    thin = not tables
    dataset = note = None
    has_binary_model = "DataModel" in z.namelist()  # .pbix import mode: model present but binary
    if thin:
        conn_src, dataset = parse_connections(z)
        if conn_src:
            connectors = {conn_src}
        elif has_binary_model:
            connectors = {"power-bi (embedded model)"}
        if has_binary_model:
            note = ("⚠ model present but stored as Power BI's binary DataModel — not machine-readable. "
                    "Export the dataset as a .pbit template (or model.bim via Tabular Editor / pbi-tools) "
                    "to recover its DAX measures and seed a Metric View.")
        elif dataset:
            note = (f"⚠ thin report — live connection to shared dataset '{dataset}'; its measures live "
                    "there. Parse that dataset's .pbit to capture them.")
        else:
            note = ("⚠ thin report — no embedded model (live connection). Export the connected "
                    "dataset's .pbit to capture its measures.")

    # measure display folders / measure tables — signals for splitting a big model (see below)
    mfolders = {m.get("displayFolder") for t in tables for m in t.get("measures", []) if m.get("displayFolder")}
    mtables = {t.get("name") for t in tables if t.get("measures")}

    fact = fact_table(model, upstream)
    fact_phys = (upstream.get(fact) or (None, None))[0] if fact else None
    cal = next((t.get("name") for t in tables if classify(t.get("name")) == "calendar"), None)

    return dict(
        name=os.path.splitext(os.path.basename(path))[0],
        measures=measures_of(model),
        fact=fact, fact_phys=fact_phys, calendar=cal,
        thin=thin, dataset=dataset, note=note,
        mfolders=mfolders, mtables=mtables, kind=os.path.splitext(path)[1].lstrip(".").lower(),
        n_tables=len(tables), n_pages=n_pages, n_visuals=n_visuals,
        n_calcs=n_calcs_of(model), params=n_params_of(model),
        datasources=max(n_src, 1),
        source=", ".join(sorted(c for c in connectors if c)) or ("live-connection" if thin else "unknown"),
        # model-only templates (measures but no visuals) read as text-free; router defaults them
        text_pct=0.0,
    )


def discover(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += glob.glob(os.path.join(p, "**", "*.pbit"), recursive=True)
            out += glob.glob(os.path.join(p, "**", "*.pbix"), recursive=True)
        elif p.lower().endswith((".pbit", ".pbix")):
            out.append(p)
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="directories and/or .pbit files")
    ap.add_argument("-o", "--out", default="mapping.yaml")
    ap.add_argument("--account", default="TODO — customer name")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    files = discover(args.paths)
    if not files:
        sys.exit("No .pbit files found in: " + ", ".join(args.paths))

    parsed, skipped = [], []
    for f in files:
        try:
            parsed.append(parse_pbit(f))
        except Exception as e:  # one unreadable report must not sink the whole stack
            skipped.append((os.path.basename(f), f"{type(e).__name__}: {e}"))
            print(f"  WARN skipped {os.path.basename(f)} — {type(e).__name__}: {e}", file=sys.stderr)
    if not parsed:
        sys.exit("No .pbit files could be parsed.")

    # group each report on its fact table; thin reports cluster with the dataset they connect to
    for r in parsed:
        r["group"] = r["fact"] or r.get("dataset") or (
            r["source"] if r["source"] not in ("unknown", "") else "live-connection (no embedded model)")

    groups = collections.defaultdict(list)
    for r in parsed:
        groups[r["group"]].append(r)

    seeds = {}
    for glabel, reps in groups.items():
        items = [(name, dax, r["name"]) for r in reps for (name, dax, _home) in r["measures"]]
        metrics, drift = seed_from_calcs(items, require_agg=False)  # DAX measures are metrics already
        cal = next((r["calendar"] for r in reps if r["calendar"]), None)
        phys = next((r["fact_phys"] for r in reps if r["fact_phys"]), None)
        title, purpose, grain = suggest_semantics(glabel, metrics, phys=phys)
        # Large single model → suggest splitting into several subject-area Metric Views (each backing
        # its own Genie space + dashboard) instead of one catch-all. Signal off display folders /
        # measure tables. Offered as a choice in interactive mode; otherwise the agent's judgment.
        allf = set().union(*[r["mfolders"] for r in reps]) if reps else set()
        allt = set().union(*[r["mtables"] for r in reps]) if reps else set()
        if len(items) >= 200 and (len(allf) >= 4 or len(allt) >= 4):
            areas = sorted(allf) or sorted(allt)
            purpose += (f"  ⚠ Large model — {len(items)} measures across {len(allf)} display folders / "
                        f"{len(allt)} measure tables (e.g. {', '.join(areas[:5])}). Consider SPLITTING into "
                        "several subject-area Metric Views, each backing its own Genie space + dashboard, "
                        "rather than one catch-all (see SKILL.md).")
        # thin group (no readable measures) → surface the export warning as the purpose
        thin_note = next((r["note"] for r in reps if r.get("thin") and r.get("note")), None)
        if (not metrics or metrics == ["TODO"]) and thin_note:
            purpose = thin_note
        seeds[glabel] = dict(
            title=title,
            core_source=(phys or glabel),
            purpose=purpose,
            grain=grain,
            time_dimension=(f"{cal} (date dimension — conformed, shared across the model)" if cal else "TODO — the date/time dimension"),
            metrics=(metrics[:12] or ["TODO"]),
            drift=drift[:12],
            shared=[],
        )

    rows = [dict(name=r["name"], group=r["group"], worksheets=r["n_pages"],
                 datasources=r["datasources"], source=r["source"], text_pct=r["text_pct"],
                 params=r["params"], n_calcs=r["n_calcs"], purpose="", drivers="")
            for r in parsed]

    mapping = route.build_mapping(rows, account=args.account, title=args.title, seeds=seeds, source_tool="Power BI")
    npbix = sum(1 for r in parsed if r.get("kind") == "pbix")
    mapping["meta"]["source_note"] = (f"Parsed directly from {len(parsed)} Power BI file(s) "
                                      f"(.pbit/.pbix{'; ' + str(npbix) + ' .pbix report+source only' if npbix else ''}) "
                                      "by the aibi-migration-map skill (parse_pbit.py).")
    route.write_mapping(mapping, args.out)

    route.summarize(mapping, f"raw parse of {len(parsed)} .pbit report(s)")
    ndrift = sum(len(mv.get("drift", [])) for mv in mapping["metric_views"].values())
    nmeas = sum(len(r["measures"]) for r in parsed)
    nthin = sum(1 for r in parsed if r.get("thin"))
    print(f"Seeded {len(mapping['metric_views'])} metric views from {nmeas} DAX measures, "
          f"{ndrift} drift signals detected.")
    if nthin:
        print(f"\n⚠ {nthin} report(s) had no machine-readable model — routed on the cheap path "
              "(report + source only, NO measures / Metric View). To capture their semantics, export more:")
        for r in parsed:
            if r.get("thin"):
                print(f"    • {r['name']} [{r['kind']}] — {r['note']}")
    if skipped:
        print(f"Skipped {len(skipped)} unreadable file(s): " + "; ".join(n for n, _ in skipped))
    print(f"Wrote {args.out} — curate it, then: python3 scripts/render.py {args.out} -o report.html")


if __name__ == "__main__":
    main()
