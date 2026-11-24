#!/usr/bin/env python3
"""author.py — STAGE 2a: author each Metric View's YAML (agent-driven), validate it, get it approved.

The Assessment only defines Metric View SHELLS and the CONCEPTS they must consolidate. The YAML is written
here, against the REAL source tables, following the live uc-semantics-patterns repo:

  author.py context  <map> <mv-key>            JSON briefing for the agent: shell, concepts + the variants found
                                               in the estate, the source table's real columns, which patterns apply
                                               (and the exact command to read each), and the authoring rules
  author.py register <map> <mv-key> <file.yaml> [--origin agent-drafted|manual]
                                               static checks, then store the YAML in the map (approval cleared)
  author.py validate <map> <mv-key>            LIVE check: create it under a throw-away name, query every measure,
                                               drop it. Nothing real is created or replaced.
  author.py show     <map> <mv-key>
  author.py approve  <map> <mv-key>            the user approved THIS yaml (only after they have seen it)
  author.py status   <map>                     authoring state of every metric view

Common flags: --profile P (omit inside Genie Code / a notebook), --offline (skip anything that talks to Databricks)
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "adapters"))
from smlib import read_yaml, write_yaml, find, h12  # noqa: E402
import design as D  # noqa: E402
import patterns as PAT  # noqa: E402

RULES = [
    "Source of truth is the patterns repo: read each recommended pattern (command given) BEFORE writing, and follow its YAML shapes.",
    "version: 1.1 (uses `fields:`; see https://docs.databricks.com/aws/en/uc-semantics/metric-views/create) — keep one `source:` and put every other table under `joins:` with `rely: at_most_one_match` when it truly holds.",
    "One measure per approved CONCEPT, named exactly like the concept (that is what Pages and Genie will cite). Add `display_name`, `comment` and `synonyms` where the concept has synonyms.",
    "Where a concept DRIFTS, use the variant in concept.chosen / concept.definition. If neither is set, STOP and ask the user which definition wins — never pick silently.",
    "Only reference columns that exist in `source_columns` (as `source.<col>`) or in a declared join. Never invent a column; if the needed column is missing, say so and leave the measure out.",
    "Do not put filters/joins you cannot justify from the estate. Do not translate formulas you cannot translate faithfully (LOD / table calcs / complex DAX context): leave that measure out and report it.",
    "Fields (dimensions): include the time dimension and the obvious grain keys; prefer a conformed calendar if the shell names one.",
    "After `register`, run `validate` and fix every reported error. Show the user the YAML (and what you left out) and only then `approve`.",
]


def load(a):
    m = read_yaml(a.map)
    mv = find(m["metric_views"], a.mv) if getattr(a, "mv", None) else None
    if getattr(a, "mv", None) and not mv:
        sys.exit(f"unknown metric view '{a.mv}'. Known: " + ", ".join(x["key"] for x in m["metric_views"]))
    return m, mv


def save(a, m):
    D.finalize(m)
    D.stamp_approvals(m)
    write_yaml(a.map, m, header=open(a.map, encoding="utf-8").read().split("meta:")[0])


def client(a):
    if a.offline:
        return None
    from dbx import DbxClient
    if getattr(a, "fake", False):
        from dbx import FakeClient
        return FakeClient()
    return DbxClient(a.profile, a.warehouse_id or (read_yaml(a.map)["meta"].get("target") or {}).get("warehouse_id"))


def cmd_context(a):
    m, mv = load(a)
    cons = {c["key"]: c for c in m["concepts"]}
    out = dict(
        metric_view=dict(key=mv["key"], fqn=mv["fqn"], source_table=mv["source_table"], grain=mv.get("grain"),
                         time_dimension=mv.get("time_dimension"), long_tail_metrics_left_out=mv.get("long_tail", [])),
        concepts=[dict(key=k, name=cons[k]["name"], approval=cons[k].get("approval"), drift=cons[k]["drift"],
                       definition=cons[k].get("definition"), chosen=cons[k].get("chosen"),
                       variants_found=[dict(formula=v["formula"], translated_hint=v.get("sql_hint"), reports=len(v["reports"]))
                                       for v in cons[k]["variants"]],
                       patterns=cons[k].get("patterns", []))
                  for k in mv["concepts"] if k in cons and cons[k].get("approval") != "rejected"],
        patterns=[], source_columns=None, rules=RULES, existing_yaml=mv.get("yaml"))
    idx = PAT.get_index()
    out["patterns_repo"] = dict(repo=idx["repo"], commit=idx["commit"], index_source=idx["source"])
    want = sorted({p for c in out["concepts"] for p in c["patterns"]} | set(mv.get("patterns", [])))
    for p in want:
        out["patterns"].append(dict(folder=p, read_with=f'python3 scripts/patterns.py show "{p}" --yml'))
    out["patterns_all"] = [p["folder"] for p in idx["patterns"]]
    c = client(a)
    if c is not None:
        try:
            out["source_columns"] = [dict(name=n, type=t) for n, t in c.table_columns(mv["source_table"])]
        except Exception as e:
            out["source_columns"] = f"UNAVAILABLE: {str(e)[:200]} — the source table must exist and be readable before authoring"
    print(json.dumps(out, indent=2, ensure_ascii=False))


def static_checks(mv, text, m, cols):
    import yaml
    errs, warns = [], []
    try:
        d = yaml.safe_load(text)
    except Exception as e:
        return [f"not valid YAML: {e}"], []
    if not isinstance(d, dict):
        return ["YAML root must be a mapping"], []
    if str(d.get("version")) not in ("1.1", "0.1", "1.0"):
        errs.append(f"version must be 1.1 (got {d.get('version')!r})")
    if not d.get("source"):
        errs.append("missing `source:`")
    ms = d.get("measures") or []
    if not ms:
        errs.append("no `measures:`")
    names = [x.get("name") for x in ms if isinstance(x, dict)]
    if any(not x.get("expr") for x in ms if isinstance(x, dict)):
        errs.append("every measure needs an `expr`")
    if len(set(n.lower() for n in names if n)) != len([n for n in names if n]):
        errs.append("duplicate measure names")
    cons = {c["key"]: c for c in m["concepts"]}
    missing = [cons[k]["name"] for k in mv["concepts"] if k in cons and cons[k].get("approval") != "rejected"
               and cons[k]["name"].lower() not in {str(n).lower() for n in names}]
    if missing:
        warns.append("concepts without a measure (say why to the user): " + ", ".join(missing))
    src = str(d.get("source"))
    if src.lower() != mv["source_table"].lower() and not src.strip().lower().startswith(("select", "with")):
        warns.append(f"source `{src}` differs from the shell's source_table `{mv['source_table']}`")
    if cols:
        known = {c.lower() for c, _ in cols}
        used = set(re.findall(r"\bsource\.`?([A-Za-z_][\w ]*?)`?(?=[\s,)+\-*/<>=]|$)", yaml.safe_dump(d)))
        bad = sorted(u for u in used if u.lower() not in known and u != "*")
        if bad:
            errs.append("columns not found on the source table: " + ", ".join(bad[:10]))
    return errs, warns


def cmd_register(a):
    m, mv = load(a)
    text = open(a.file, encoding="utf-8").read()
    c = client(a)
    cols = None
    if c is not None:
        try:
            cols = c.table_columns(mv["source_table"])
        except Exception as e:
            print(f"  (could not read source columns: {str(e)[:120]} — column check skipped)", file=sys.stderr)
    errs, warns = static_checks(mv, text, m, cols)
    for w in warns:
        print("WARN:", w)
    if errs:
        for e in errs:
            print("ERROR:", e, file=sys.stderr)
        sys.exit("not registered — fix the errors above")
    mv["yaml"], mv["yaml_origin"] = text.strip() + "\n", a.origin
    mv.pop("yaml_approved_hash", None)
    D.finalize(m)
    mv["yaml_concept_hash"] = mv["concept_hash"]
    save(a, m)
    print(f"registered YAML for {mv['key']} ({a.origin}); next: validate, show it to the user, then approve")


def cmd_validate(a):
    from apply import validate_mv
    from dbx import ApiError
    m, mv = load(a)
    if not mv.get("yaml"):
        sys.exit("no YAML registered yet")
    c = client(a)
    if c is None:
        sys.exit("validate needs a workspace connection (drop --offline)")
    try:
        validate_mv(c, mv["fqn"], mv["yaml"], mv["key"])
    except ApiError as e:
        sys.exit(f"INVALID: {e}")
    print(f"OK — {mv['fqn']} would create cleanly and all {len(__import__('apply').mv_measures(mv['yaml']))} measures evaluate. (Nothing was created.)")


def cmd_show(a):
    m, mv = load(a)
    print(mv.get("yaml") or "(no YAML yet)")


def cmd_approve(a):
    m, mv = load(a)
    if not mv.get("yaml"):
        sys.exit("no YAML to approve")
    if mv.get("yaml_concept_hash") != mv.get("concept_hash"):
        sys.exit("the concept decisions changed since this YAML was authored — re-author (context → register) first")
    mv["yaml_approved_hash"] = h12(mv["yaml"])
    save(a, m)
    print(f"approved YAML for {mv['key']}")


def cmd_status(a):
    m, _ = load(a)
    for mv in m["metric_views"]:
        print(f"{mv['key']:<46} shell={mv.get('approval'):<9} authoring={mv.get('authoring')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--warehouse-id", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for n, f in (("context", cmd_context), ("validate", cmd_validate), ("show", cmd_show), ("approve", cmd_approve)):
        p = sp.add_parser(n); p.add_argument("map"); p.add_argument("mv"); p.set_defaults(fn=f)
    p = sp.add_parser("register"); p.add_argument("map"); p.add_argument("mv"); p.add_argument("file")
    p.add_argument("--origin", default="agent-drafted", choices=["agent-drafted", "manual"]); p.set_defaults(fn=cmd_register)
    p = sp.add_parser("status"); p.add_argument("map"); p.set_defaults(fn=cmd_status)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
