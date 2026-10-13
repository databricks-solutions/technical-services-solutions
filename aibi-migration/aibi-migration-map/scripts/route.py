#!/usr/bin/env python3
"""
route.py — routing rule + mapping builder (shared library + CSV entry point).

The PRIMARY inputs are raw BI files — point `scripts/parse_twbx.py` (Tableau) or
`scripts/parse_pbit.py` (Power BI) at a folder of exported files (e.g. a scanned Volume)
and they parse the files directly and call `build_mapping()` here. This file also accepts
a hand-filled inventory CSV (see `references/input-schema.md`) for estates with no raw files.

Routing is PURPOSE-ONLY — it answers "what should this become on Databricks?", not
"how hard is it?" (no complexity / effort / compatibility scoring). It assumes every
report is in use and every source is movable, so every workbook gets a real home.
Override any single call by editing `target:` in the emitted YAML.

Usage (CSV path):
  python3 route.py INVENTORY.csv -o mapping.yaml [--account NAME] [--title TITLE]
"""
import csv, sys, re, argparse
try:
    import yaml
except ImportError:
    sys.exit("Needs pyyaml.  pip install pyyaml")

# ---- routing rule --------------------------------------------------------
MONITOR_RE = re.compile(r"error|exception|monitor|status|health|sync|invalid|missing|alert|breach", re.I)
APP_PARAM_MIN = 3      # params-as-inputs threshold
APP_CALC_MIN  = 40     # what-if tools carry heavy calc logic
GENIE_TEXT_PCT = 0.95  # ≥95% text marks = crosstab reader
GENIE_MAX_DS   = 2

KIND_LABEL = {"dashboard": "Dashboards", "genie": "Q&A / Genie", "app": "App", "alert": "Ops Alerts"}


def route(wb):
    """wb: normalized dict -> (kind, reason). Purpose-only; no complexity signal."""
    if wb.get("params", 0) >= APP_PARAM_MIN and wb.get("n_calcs", 0) > APP_CALC_MIN:
        return "app", f"params-as-inputs ({wb['params']}) + calc>{APP_CALC_MIN}"
    if MONITOR_RE.search(wb.get("name", "")) or MONITOR_RE.search(wb.get("purpose", "")):
        return "alert", "exception/monitor purpose"
    if wb.get("text_pct", 0.0) >= GENIE_TEXT_PCT and wb.get("datasources", 99) <= GENIE_MAX_DS:
        return "genie", f"≥{int(GENIE_TEXT_PCT*100)}% text marks, ≤{GENIE_MAX_DS} sources"
    return "dashboard", "default"


def slug_group(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:28] or "misc"


# ---- mapping builder (shared by the CSV path and parse_twbx.py) ----------
def _blank_mv(group_label):
    return dict(title=f"TODO — {group_label} metrics", load_bearing=False,
                core_source="TODO", purpose="TODO — what this Metric View standardizes.",
                grain="TODO", metrics=["TODO"], time_dimension="TODO — the date/time dimension",
                drift=[], shared=[], owner="TODO")


def build_mapping(rows, account="TODO — customer name", title=None, seeds=None, source_tool="Tableau"):
    """rows: list of normalized workbook dicts. Each carries at least:
         name, group (label), worksheets, source, params, n_calcs, text_pct, datasources,
         purpose (optional), drivers (optional).
       seeds: optional {group_label: {core_source, purpose, metrics, drift, time, shared, grain}}
         — the raw-parse path fills these from real calc fields; the CSV path leaves them blank.
       Returns the mapping dict ready for yaml.safe_dump / render.py.
    """
    seeds = seeds or {}
    groups, assets, mviews, workbooks = {}, {}, {}, []
    for wb in rows:
        g = wb.get("group") or wb.get("folder") or "Ungrouped"
        gid = slug_group(g)
        groups.setdefault(gid, g)
        mvid = f"MV-{gid}"
        if mvid not in mviews:
            s = seeds.get(g) or seeds.get(gid) or {}
            mv = _blank_mv(g)
            for k in ("title", "core_source", "purpose", "grain", "time_dimension", "metrics", "drift", "shared"):
                if s.get(k):
                    mv[k] = s[k]
            mviews[mvid] = mv
        kind, reason = route(wb)
        aid = f"{kind[:4].upper()}-{gid}"
        assets.setdefault(aid, dict(name=f"{g} — {KIND_LABEL[kind]}", kind=kind, metric_view=mvid))
        workbooks.append(dict(name=wb["name"], group=gid,
                              worksheets=int(wb.get("worksheets", 0)),
                              source=wb.get("source", "—"),
                              target=aid, _suggested=f"{kind} ({reason})"))

    # an MV that backs ≥2 assets is load-bearing — mark it so (the report tags these)
    mv_asset_count = {}
    for a in assets.values():
        mv = a.get("metric_view")
        if mv:
            mv_asset_count[mv] = mv_asset_count.get(mv, 0) + 1
    for mvid, mv in mviews.items():
        mv["load_bearing"] = mv_asset_count.get(mvid, 0) >= 2

    mapping = dict(
        meta=dict(
            title=title or f"{account} — {source_tool} → Databricks Migration Map",
            account=account, source_tool=source_tool,
            subtitle="Every workbook mapped to the Databricks asset that replaces it, "
                     "consolidated onto a shared Metric View semantic layer.",
            assumptions=[
                dict(label="Assumption 1", text="All reports assumed in use — nothing retired for low usage. Duplicates still fold in."),
                dict(label="Assumption 2", text="All data assumed movable to Databricks — external sources are targets, not blockers. Routing is purpose-only."),
            ],
            why="Metric logic today is copy-pasted across the estate and drifting. Each Metric View "
                "below is the one place a definition lives, so a dashboard, a Genie space, and an App "
                "all return the same number."),
        groups=groups, metric_views=mviews, assets=assets, workbooks=workbooks)
    return mapping


HEADER = ("# Starter mapping — CURATE before rendering:\n"
          "#   • merge/rename/split assets (auto-made one per group×kind)\n"
          "#   • groups are seeded on shared fact tables — rename to business subject areas\n"
          "#   • Metric Views are seeded from real calc fields + detected drift — refine titles/owners\n"
          "#   • set target: RETIRE (+ survivor:) on duplicate workbooks\n"
          "#   • the _suggested field on each workbook is the routing rationale — delete once reviewed\n\n")


def write_mapping(mapping, out):
    with open(out, "w") as f:
        f.write(HEADER)
        yaml.safe_dump(mapping, f, sort_keys=False, allow_unicode=True, width=100)


def summarize(mapping, source_label):
    kinds = {}
    for w in mapping["workbooks"]:
        k = mapping["assets"][w["target"]]["kind"]
        kinds[k] = kinds.get(k, 0) + 1
    print(f"Parsed {len(mapping['workbooks'])} workbooks ({source_label}).")
    print(f"Routed → {dict(sorted(kinds.items()))} across {len(mapping['groups'])} groups, "
          f"{len(mapping['assets'])} draft assets, {len(mapping['metric_views'])} metric views.")


# ---- CSV input parsing (hand-filled template — secondary path) -----------
def parse_row(r):
    tp = r.get("text_pct", "")
    try:
        tp = float(tp)
    except (TypeError, ValueError):
        tp = 1.0 if str(tp).strip().lower() in ("y", "yes", "true", "crosstab") else 0.0
    return dict(name=r["workbook"].strip(), folder=r.get("folder", "").strip(),
                worksheets=int(r.get("worksheets") or 0), datasources=int(r.get("datasources") or 1),
                text_pct=tp, source=(r.get("source", "").strip() or "unknown"),
                params=int(r.get("params") or 0), n_calcs=int(r.get("n_calcs") or 0),
                purpose=r.get("purpose", "").strip(), drivers="", group=r.get("group", "").strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory")
    ap.add_argument("-o", "--out", default="mapping.yaml")
    ap.add_argument("--account", default="TODO — customer name")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    with open(args.inventory, newline="") as f:
        rd = csv.DictReader(f)
        rows = [parse_row(r) for r in rd if r.get("workbook", "").strip()]
        # provisional group = folder (CSV path has no fact-table info)
        for wb in rows:
            wb["group"] = wb["group"] or wb["folder"] or "Ungrouped"

    mapping = build_mapping(rows, account=args.account, title=args.title)
    write_mapping(mapping, args.out)
    summarize(mapping, "hand-filled inventory")
    print(f"Wrote {args.out} — curate it, then: python3 scripts/render.py {args.out} -o report.html")


if __name__ == "__main__":
    main()
