#!/usr/bin/env python3
"""design.py — ASSESSMENT: inventory.json (+ previous map, + decisions) → semantic-map.yaml

The semantic map is the *desired state* of the UC semantic foundation. The Assessment defines the
OVER-ARCHING CONCEPTS that need semantic consolidation — "Net Revenue" used by 6 reports in 3 different
ways — and where they should live (Domain → Metric View shell → Page). It does NOT write Metric View YAML:
that is authored in Stage 2 against the real tables, following the live uc-semantics-patterns repo.

  Domains / Subdomains   business areas (built on governed tags)
  Concepts               metrics referenced by ≥2 reports, or defined >1 way (drift) — the consolidation work
  Metric View shells     the home each concept moves to (name, source table, concepts) — no YAML yet
  Pages                  authoritative definition per concept (+ glossary terms from documents)
  Wikis                  table documentation for each shell's source table
  Asset tags             binds MV + source table into their domain

Re-running is safe and stable (idempotent):
  * objects keep a key derived from evidence (e.g. a fact table), so renaming never changes identity;
  * derived fields are regenerated, but a field a human changed (decisions, or edited in the yaml) is pinned;
  * objects that vanish from the inputs become `status: orphaned`, never deleted;
  * `manual` objects are never touched;  no timestamps ⇒ identical inputs give a byte-identical file.

Usage:
  design.py output/inventory.json -o output/semantic-map.yaml
            [--config design.yaml] [--catalog C] [--schema S] [--warehouse-id W] [--decisions decisions.json]
            [--include-singletons]   # also make concepts of metrics used by only one report
"""
import argparse
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "adapters"))
from smlib import (slug, humanize, h12, read_json, read_yaml, write_yaml, spec_hash, DERIVED_FIELDS,  # noqa: E402
                   SCHEMA_VERSION, KINDS, find)
from parse_common import base_caption, norm_formula, is_metric  # noqa: E402
import patterns as PAT  # noqa: E402

PLACEHOLDER_CAT = "<catalog>"

# ---- tiny, SAFE formula translator: only 1:1 aggregations over one column (used as an authoring HINT) ----
_TAB = re.compile(r"^\s*(SUM|AVG|MIN|MAX|COUNT|COUNTD)\s*\(\s*\[([^\]\[]+)\]\s*\)\s*$", re.I)
_DAX = re.compile(r"^\s*(SUM|AVERAGE|MIN|MAX|COUNT|DISTINCTCOUNT)\s*\(\s*'?[^'\[\]]+'?\[([^\]]+)\]\s*\)\s*$", re.I)
_FN = {"SUM": "SUM", "AVG": "AVG", "AVERAGE": "AVG", "MIN": "MIN", "MAX": "MAX", "COUNT": "COUNT"}


def simple_expr(formula):
    m = _TAB.match(formula or "") or _DAX.match(formula or "")
    if not m:
        return None
    fn, col = m.group(1).upper(), m.group(2).strip()
    c = f"source.`{col}`"
    return f"COUNT(DISTINCT {c})" if fn in ("COUNTD", "DISTINCTCOUNT") else f"{_FN[fn]}({c})"


def fact_of(r):
    return (r.get("fact_tables") or [None])[0]


def schema_of(fact):
    parts = (fact or "").split(".")
    return parts[-2] if len(parts) >= 2 else None


def table_of(fact):
    return (fact or "").split(".")[-1]


def uc_table(fact, cfg):
    """Where the source table lives in UC. cfg.table_map overrides; else <catalog>.<source schema>.<table>."""
    tm = cfg.get("table_map") or {}
    if fact in tm:
        return tm[fact]
    cat = (cfg.get("target") or {}).get("catalog") or PLACEHOLDER_CAT
    return f"{cat}.{schema_of(fact) or 'default'}.{table_of(fact)}"


# ---- fresh design from the inventory ------------------------------------------------------
def build_fresh(inv, cfg, include_singletons=False):  # noqa: C901
    tgt = cfg.get("target") or {}
    cat, sch = tgt.get("catalog") or PLACEHOLDER_CAT, tgt.get("schema") or "semantic"
    pre = slug(tgt.get("tag_prefix") or "", "_") + "_" if tgt.get("tag_prefix") else ""   # namespace domain tags in shared accounts

    # Power BI often reports a bare table name; Tableau a schema-qualified one. Same physical table ⇒ one group.
    qualified = collections.defaultdict(set)
    for r in inv["reports"]:
        f = fact_of(r)
        if f and "." in f:
            qualified[table_of(f).lower()].add(f)

    def canon_fact(f):
        if f and "." not in f and len(qualified.get(f.lower(), ())) == 1:
            return next(iter(qualified[f.lower()]))
        return f

    groups = collections.defaultdict(list)
    for r in inv["reports"]:
        groups[canon_fact(fact_of(r)) or "ungrouped"].append(r)
    real = {g: rs for g, rs in groups.items() if g != "ungrouped"}
    by_schema = collections.defaultdict(list)
    for g in real:
        by_schema[schema_of(g)].append(g)

    D, C, MV, PG, WK, AT = [], [], [], [], [], []

    for sc, gs in sorted(by_schema.items(), key=lambda kv: str(kv[0])):
        if sc and len(gs) >= 2:
            D.append(dict(key=f"dom-schema-{slug(sc)}", tag_key=pre + slug(sc), parent=None, name=humanize(sc),
                          subtitle=f"{len(gs)} subject areas on schema {sc}",
                          description=f"Everything built on schema `{sc}`: " + ", ".join(sorted(table_of(g) for g in gs)) + ".",
                          evidence=dict(schema=sc), source="derived"))
    parents = {sc for sc, gs in by_schema.items() if sc and len(gs) >= 2}

    for g, rs in sorted(real.items()):
        sc = schema_of(g)
        dkey = f"dom-{slug(g)}"
        parent = f"dom-schema-{slug(sc)}" if sc in parents else None
        leaf = slug(humanize(table_of(g)))
        tag = f"{pre}{slug(sc)}/{leaf}" if parent else pre + leaf
        D.append(dict(key=dkey, tag_key=tag, parent=parent, name=humanize(table_of(g)),
                      subtitle=f"{len(rs)} report(s) · {g}", source="derived",
                      description=(f"Business area built on `{g}`. Absorbs: " + ", ".join(sorted(r['name'] for r in rs)[:8])
                                   + ("…" if len(rs) > 8 else "") + "."),
                      evidence=dict(fact_table=g, reports=sorted(r["id"] for r in rs))))

        # -- concepts: every metric, with the distinct definitions found in the estate
        byname = collections.defaultdict(lambda: collections.defaultdict(set))
        raw = {}
        for r in rs:
            for m in r["measures"]:
                b = base_caption(m["name"])
                if b and is_metric(b, m["formula"], require_agg=(r["tool"] == "tableau")):
                    nf = simple_expr(m["formula"]) or norm_formula(m["formula"])  # same meaning in Tableau/DAX ≠ drift
                    byname[b][nf].add(r["id"])
                    raw.setdefault((b, nf), m["formula"])
        mvkey = f"mv-{slug(g)}"
        concept_keys, long_tail = [], []
        for b in sorted(byname, key=str.lower):
            variants = [dict(formula=raw[(b, nf)], sql_hint=simple_expr(raw[(b, nf)]), reports=sorted(ids))
                        for nf, ids in sorted(byname[b].items())]
            reps = sorted({i for v in variants for i in v["reports"]})
            drift = len(variants) > 1
            if len(reps) < 2 and not drift and not include_singletons:
                long_tail.append(b)
                continue
            ck = f"cn-{slug(g)}-{slug(b)}"
            concept_keys.append(ck)
            C.append(dict(key=ck, name=b, domain=dkey, fact_table=g, mv=mvkey, source="derived", variants=variants,
                          reports=reps, drift=drift,
                          need=("high" if drift else "medium" if len(reps) >= 3 else "low"),
                          patterns=PAT.match(b), definition="", chosen=None,
                          evidence=dict(fact_table=g, metric=b)))
            # -- one authoritative-definition Page per concept
            rows = "\n".join(f"| `{v['formula']}` | {', '.join(v['reports'])} |" for v in variants)
            PG.append(dict(key=f"pg-{slug(g)}-{slug(b)}", domain=dkey, source="derived", title=b, synonyms=[],
                           description=(f"Authoritative definition of {b} — currently defined {len(variants)} different ways."
                                        if drift else f"Authoritative definition of {b}, used by {len(reps)} reports."),
                           body=(f"## {b}\n\n**Status:** _definition to be confirmed by the business owner._\n\n"
                                 f"Found {len(variants)} variant(s) across {len(reps)} report(s):\n\n"
                                 f"| Formula | Reports |\n|---|---|\n{rows}\n"),
                           related=[mvkey], sources=[], evidence=dict(metric=b, fact_table=g)))
        cal = next((r["calendar"] for r in rs if r.get("calendar")), None)
        if concept_keys:
            pats = sorted({p for c in C if c["key"] in concept_keys for p in c["patterns"]})
            mvname = f"mv_{slug(humanize(table_of(g)))}"
            ndrift = sum(1 for c in C if c["key"] in concept_keys and c["drift"])
            MV.append(dict(
                key=mvkey, title=f"MV {humanize(table_of(g))}", domain=dkey, source="derived",
                fqn=f"{cat}.{sch}.{mvname}", source_table=uc_table(g, cfg),
                grain=f"One row per {humanize(table_of(g)).lower()} record — confirm the true grain.",
                purpose=f"Single home for {len(concept_keys)} concept(s) computed on {g}" + (f" ({ndrift} drift today)." if ndrift else "."),
                time_dimension=cal, concepts=concept_keys, long_tail=long_tail, patterns=pats, joins=[], filter=None,
                absorbs=sorted(r["id"] for r in rs), evidence=dict(fact_table=g, reports=sorted(r["id"] for r in rs))))
            for sec, nm in (("table", f"{cat}.{sch}.{mvname}"), ("table", uc_table(g, cfg))):
                AT.append(dict(key=f"at-{slug(nm)}-{slug(tag)}", securable=sec, name=nm, tag_key=tag, tag_value="",
                               domain=dkey, source="derived", evidence=dict(fact_table=g)))
            WK.append(dict(key=f"wk-{slug(g)}", table=uc_table(g, cfg), source="derived",
                           body=(f"# {humanize(table_of(g))}\n\nSource table behind **MV {humanize(table_of(g))}**.\n\n"
                                 f"**Used by {len(rs)} report(s):** " + ", ".join(sorted(r['name'] for r in rs)) +
                                 f"\n\n**Calendar:** {cal or 'n/a'}\n"), evidence=dict(fact_table=g)))

    dom_by_name = {slug(d["name"]): d["key"] for d in D}
    for t in inv.get("glossary_terms", []):
        term = t.get("term")
        if not term:
            continue
        dk = dom_by_name.get(slug(t.get("domain_hint") or ""), "general")
        PG.append(dict(key=f"pg-term-{slug(term)}", domain=dk, source="derived", title=term,
                       synonyms=sorted(t.get("synonyms") or []), description=(t.get("definition") or "")[:280],
                       body=f"## {term}\n\n{t.get('definition', '')}\n", related=[],
                       sources=[t.get("source")] if t.get("source") else [], evidence=dict(term=term)))

    report_map = []
    for r in sorted(inv["reports"], key=lambda r: r["id"]):
        g = canon_fact(fact_of(r)) or "ungrouped"
        mine = [c["name"] for c in C if r["id"] in c["reports"]]
        report_map.append(dict(report=r["id"], name=r["name"], tool=r["tool"], thin=r.get("thin", False),
                               note=r.get("note", ""), domain=(f"dom-{slug(g)}" if g != "ungrouped" else None),
                               metric_view=(f"mv-{slug(g)}" if any(m["key"] == f"mv-{slug(g)}" for m in MV) else None),
                               n_measures=len(r["measures"]), concepts=sorted(mine)))
    return dict(domains=D, concepts=C, metric_views=MV, pages=PG, wikis=WK, asset_tags=AT, report_map=report_map)


# ---- idempotent merge ---------------------------------------------------------------------
SCALAR_GEN = {"domains": ["name", "subtitle", "description"], "metric_views": ["title", "purpose", "grain"],
              "concepts": ["name"], "pages": ["title", "description", "body"], "wikis": ["body"], "asset_tags": []}


def gen_hashes(kind, obj, pinned):
    return {f: h12(obj.get(f)) for f in SCALAR_GEN[kind] if f in obj and f not in pinned}


def merge_kind(kind, prev, fresh):
    pk = {x["key"]: x for x in prev}
    out, seen = [], set()
    for f in sorted(fresh, key=lambda x: x["key"]):
        seen.add(f["key"])
        p = pk.get(f["key"])
        if p is None:
            out.append(dict(f, approval="proposed", _gen=gen_hashes(kind, f, set())))
            continue
        if p.get("source") == "manual":
            out.append(p)
            continue
        m = dict(p)
        m.pop("status", None)
        pinned = set(p.get("pinned") or [])
        # auto-pin: a derived scalar that no longer matches what WE generated last time was hand-edited
        gen = p.get("_gen") or {}
        for fld, hg in gen.items():
            if fld in p and h12(p[fld]) != hg:
                pinned.add(fld)
        if pinned:
            m["pinned"] = sorted(pinned)
        for fld in DERIVED_FIELDS[kind]:
            if fld in pinned or fld not in f:
                continue
            m[fld] = f[fld]
        if kind == "asset_tags":
            m["tag_value"] = p.get("tag_value", f.get("tag_value", ""))
        m["_gen"] = gen_hashes(kind, m, pinned)
        out.append(m)
    for k, p in sorted(pk.items()):
        if k in seen:
            continue
        out.append(p if p.get("source") == "manual" else dict(p, status="orphaned"))
    return out


def apply_decisions(m, decisions):
    """decisions: {"decisions":[{kind,key,approval?,note?,set?{field:value},}]}  (from the HTML report or decide.py)"""
    n = 0
    for d in (decisions or {}).get("decisions", []):
        item = find(m.get(d["kind"], []), d["key"])
        if not item:
            print(f"  WARN decision for unknown {d['kind']}/{d['key']} ignored", file=sys.stderr)
            continue
        for fld, val in (d.get("set") or {}).items():
            item[fld] = val
            item["pinned"] = sorted(set(item.get("pinned") or []) | {fld})
        if d.get("note") is not None:
            item["note"] = d["note"]
        st = d.get("approval")
        if st:
            item["approval"] = st
            if st == "approved":
                item["_approve"] = True  # hash is stamped after finalize(), once derived fields settle
            else:
                item.pop("approved_hash", None)
        n += 1
    return n


def finalize(m, cfg=None):
    """Compute readiness + blockers (informational; apply.py re-checks)."""
    doms = {d["key"]: d for d in m["domains"]}
    cons = {c["key"]: c for c in m["concepts"]}
    for c in m["concepts"]:
        c["blockers"] = []
        if c.get("chosen") and c["chosen"] not in [v["formula"] for v in c.get("variants", [])]:
            c["blockers"].append("chosen definition no longer among the variants found")
    for mv in m["metric_views"]:
        bl = []
        if PLACEHOLDER_CAT in mv["fqn"]:
            bl.append("set target.catalog (design.yaml or --catalog)")
        if not [k for k in mv.get("concepts", []) if k in cons and cons[k].get("approval") != "rejected"]:
            bl.append("no concepts left")
        mv["blockers"] = bl
        if "comment" not in (mv.get("pinned") or []):
            mv["comment"] = mv.get("purpose")
        # the decisions the YAML must honour (which definition wins for each concept) — if they change, re-author
        mv["concept_hash"] = h12([[k, cons[k].get("chosen"), cons[k].get("definition"), cons[k].get("approval") == "rejected"]
                                  for k in mv.get("concepts", []) if k in cons])
        y = mv.get("yaml")
        if y and mv.get("yaml_concept_hash") != mv["concept_hash"]:
            mv["authoring"] = "STALE — concept decisions changed since the YAML was authored; re-author"
        else:
            mv["authoring"] = ("approved" if y and mv.get("yaml_approved_hash") == h12(y)
                               else "drafted (awaiting approval)" if y else "pending (Stage 2)")
        mv["ready"] = not bl
    for p in m["pages"]:
        p["blockers"] = [] if (p["domain"] == "general" or p["domain"] in doms) else ["domain missing"]
    for w in m["wikis"]:
        w["blockers"] = ["set target.catalog (design.yaml or --catalog)"] if PLACEHOLDER_CAT in w["table"] else []
    for a in m["asset_tags"]:
        a["blockers"] = ["set target.catalog (design.yaml or --catalog)"] if PLACEHOLDER_CAT in a["name"] else []
    for d in m["domains"]:
        d["blockers"] = [] if (d.get("parent") is None or d["parent"] in doms) else ["parent domain missing"]
    return m


def stamp_approvals(m):
    for k in KINDS:
        for x in m[k]:
            if x.pop("_approve", False):
                x["approved_hash"] = spec_hash(k, x)


def load_cfg(a):
    cfg = read_yaml(a.config, {}) if getattr(a, "config", None) else {}
    t = cfg.setdefault("target", {})
    for k in ("catalog", "schema", "warehouse_id", "tag_prefix"):
        v = getattr(a, k, None)
        if v:
            t[k] = v
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inventory")
    ap.add_argument("-o", "--out", default="output/semantic-map.yaml")
    ap.add_argument("--config", default=None, help="design.yaml (target catalog/schema, table_map, owners)")
    ap.add_argument("--catalog", default=None)
    ap.add_argument("--schema", default=None, help="schema that will hold the Metric Views (default: semantic)")
    ap.add_argument("--warehouse-id", dest="warehouse_id", default=None)
    ap.add_argument("--tag-prefix", dest="tag_prefix", default=None, help="prefix for governed domain tags (namespace in shared accounts)")
    ap.add_argument("--decisions", default=None, help="decisions.json exported from the HTML report")
    ap.add_argument("--include-singletons", action="store_true")
    a = ap.parse_args()

    inv = read_json(a.inventory)
    cfg = load_cfg(a)
    prev = read_yaml(a.out, {}) or {}
    fresh = build_fresh(inv, cfg, a.include_singletons)
    t = cfg["target"]

    m = dict(meta=dict(schema_version=SCHEMA_VERSION, account=inv.get("account"),
                       title=f"{inv.get('account', 'Customer')} — UC Semantics Migration Map",
                       target=dict(catalog=t.get("catalog"), schema=t.get("schema", "semantic"), warehouse_id=t.get("warehouse_id"), tag_prefix=t.get("tag_prefix")),
                       notes=(prev.get("meta") or {}).get("notes", [])))
    for k in KINDS:
        m[k] = merge_kind(k, prev.get(k, []), fresh[k])
    m["report_map"] = fresh["report_map"]
    finalize(m, cfg)
    n = apply_decisions(m, read_json(a.decisions)) if a.decisions else 0
    finalize(m, cfg)
    stamp_approvals(m)

    write_yaml(a.out, m, header=("# UC Semantics Migration Map — DESIGN (desired state).\n"
                                 "# Edit freely: fields you change are pinned and survive re-runs of design.py.\n"
                                 "# Nothing here touches Databricks until apply.py runs on `approval: approved` objects.\n"))
    c = {k: len(m[k]) for k in KINDS}
    orph = sum(1 for k in KINDS for x in m[k] if x.get("status") == "orphaned")
    drift = sum(1 for x in m["concepts"] if x.get("drift") and x.get("status") != "orphaned")
    print(f"semantic map: {c}  drifting_concepts={drift} orphaned={orph} decisions_applied={n} → {a.out}")


if __name__ == "__main__":
    main()
