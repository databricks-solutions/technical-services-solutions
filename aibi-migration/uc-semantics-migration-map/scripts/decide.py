#!/usr/bin/env python3
"""decide.py — review the design from CHAT: list, approve, reject, edit. No browser required.

The HTML report is one way for people to review; this is the other — built for an agent relaying the user's
words ("approve everything in Sales, rename the Inventory domain, Net Revenue should use the net-of-returns one").

  decide.py summary <map>                                   counts + what still needs a decision
  decide.py list    <map> [--kind K] [--approval A] [--json]
  decide.py show    <map> <kind> <key>                      one object in full
  decide.py approve <map> (--all | --kind K [--keys a,b] [--drift-free]) [--note "…"]
  decide.py reject  <map> --kind K --keys a,b
  decide.py set     <map> <kind> <key> field=value [field=value …]      (pins the field; a concept's `chosen` /
                                                                       `definition` settle a drifting metric)
  decide.py choose  <map> <concept-key> <variant-number>    pick one of the variants found (1-based) as THE definition
  decide.py import  <map> decisions.json                    fold in a decisions.json downloaded from the HTML report
  decide.py add-note <map> <kind> <key> "text"

Every change re-runs the readiness checks and re-stamps approval hashes, then rewrites the map in place.
Nothing here talks to Databricks.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "adapters"))
from smlib import read_yaml, write_yaml, find, KINDS, read_json  # noqa: E402
import design as D  # noqa: E402


def load(a):
    return read_yaml(a.map)


def save(a, m):
    D.finalize(m)
    D.stamp_approvals(m)
    D.finalize(m)
    head = open(a.map, encoding="utf-8").read().split("meta:")[0]
    write_yaml(a.map, m, header=head)


def label(k, o):
    return o.get("name") or o.get("title") or o.get("table") or o["key"]


def cmd_summary(a):
    m = load(a)
    print(f"{m['meta']['title']}  (target: {m['meta']['target'].get('catalog') or '<catalog NOT SET>'}.{m['meta']['target'].get('schema')})")
    for k in KINDS:
        items = [o for o in m[k] if o.get("status") != "orphaned"]
        c = {}
        for o in items:
            c[o.get("approval", "proposed")] = c.get(o.get("approval", "proposed"), 0) + 1
        orph = len(m[k]) - len(items)
        print(f"  {k:<13} {len(items):>3}   " + ", ".join(f"{v} {s}" for s, v in sorted(c.items())) + (f"   (+{orph} orphaned)" if orph else ""))
    drift = [c for c in m["concepts"] if c.get("drift") and c.get("status") != "orphaned" and not c.get("chosen") and not c.get("definition")]
    if drift:
        print(f"\n{len(drift)} drifting concept(s) still need a decision (decide.py choose):")
        for c in drift:
            print(f"  - {c['name']}  [{c['key']}]  {len(c['variants'])} variants across {len(c['reports'])} reports")
    bl = [(k, o) for k in KINDS for o in m[k] if o.get("blockers") and o.get("status") != "orphaned"]
    if bl:
        print(f"\nBlocked objects ({len(bl)}):")
        for k, o in bl[:12]:
            print(f"  - {k}/{o['key']}: " + "; ".join(o["blockers"]))
    mvs = [x for x in m["metric_views"] if x.get("status") != "orphaned"]
    if mvs:
        print("\nMetric views (YAML authoring is Stage 2):")
        for mv in mvs:
            print(f"  - {mv['key']}  shell={mv.get('approval')}  authoring={mv.get('authoring')}")


def cmd_list(a):
    m = load(a)
    rows = []
    for k in ([a.kind] if a.kind else KINDS):
        for o in m[k]:
            if a.approval and o.get("approval", "proposed") != a.approval:
                continue
            rows.append(dict(kind=k, key=o["key"], name=label(k, o), approval=o.get("approval", "proposed"),
                             status=o.get("status"), blockers=o.get("blockers", [])))
    if a.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        for r in rows:
            print(f"{r['kind']:<13} {r['approval']:<9} {r['key']:<52} {r['name']}" + (f"   ⚠ {'; '.join(r['blockers'])}" if r["blockers"] else ""))


def cmd_show(a):
    o = find(load(a)[a.kind], a.key)
    if not o:
        sys.exit("not found")
    print(json.dumps(o, indent=1, ensure_ascii=False, default=str))


def _decide(a, approval):
    m = load(a)
    keys = set(a.keys.split(",")) if a.keys else None
    n = 0
    for k in ([a.kind] if a.kind else KINDS):
        for o in m[k]:
            if o.get("status") == "orphaned" or (keys is not None and o["key"] not in keys):
                continue
            if keys is None and not getattr(a, "all", False):
                continue
            if getattr(a, "drift_free", False) and k == "concepts" and o.get("drift") and not (o.get("chosen") or o.get("definition")):
                continue
            if approval == "approved" and o.get("blockers"):
                continue
            o["approval"] = approval
            if approval == "approved":
                o["_approve"] = True
            else:
                o.pop("approved_hash", None)
            if getattr(a, "note", None):
                o["note"] = a.note
            n += 1
    save(a, m)
    print(f"{approval}: {n} object(s)")


def cmd_approve(a):
    if not (a.all or a.kind):
        sys.exit("say what to approve: --all or --kind K [--keys …]")
    _decide(a, "approved")


def cmd_reject(a):
    if not a.keys:
        sys.exit("--keys required")
    _decide(a, "rejected")


def _coerce(v):
    if v.lower() in ("null", "none", ""):
        return None
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def cmd_set(a):
    m = load(a)
    o = find(m[a.kind], a.key)
    if not o:
        sys.exit("not found")
    for kv in a.pairs:
        f, _, v = kv.partition("=")
        o[f] = _coerce(v)
        o["pinned"] = sorted(set(o.get("pinned") or []) | {f})
    if o.get("approval") == "approved":
        o["_approve"] = True   # an explicit edit through here is the user's decision: keep it approved
    save(a, m)
    print(f"set {a.kind}/{a.key}: {', '.join(a.pairs)}")


def cmd_choose(a):
    m = load(a)
    c = find(m["concepts"], a.concept)
    if not c:
        sys.exit("concept not found")
    i = int(a.variant) - 1
    if not 0 <= i < len(c["variants"]):
        sys.exit(f"variant must be 1..{len(c['variants'])}")
    c["chosen"] = c["variants"][i]["formula"]
    c["pinned"] = sorted(set(c.get("pinned") or []) | {"chosen"})
    c["approval"] = "approved"
    c["_approve"] = True
    save(a, m)
    print(f"{c['name']}: chose variant {a.variant} → {c['chosen']}")


def cmd_import(a):
    m = load(a)
    n = D.apply_decisions(m, read_json(a.file))
    save(a, m)
    print(f"imported {n} decision(s)")


def cmd_note(a):
    m = load(a)
    o = find(m[a.kind], a.key)
    o["note"] = a.text
    save(a, m)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("summary"); p.add_argument("map"); p.set_defaults(fn=cmd_summary)
    p = sp.add_parser("list"); p.add_argument("map"); p.add_argument("--kind", choices=KINDS); p.add_argument("--approval")
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_list)
    p = sp.add_parser("show"); p.add_argument("map"); p.add_argument("kind", choices=KINDS); p.add_argument("key"); p.set_defaults(fn=cmd_show)
    for n, f in (("approve", cmd_approve), ("reject", cmd_reject)):
        p = sp.add_parser(n); p.add_argument("map"); p.add_argument("--all", action="store_true"); p.add_argument("--kind", choices=KINDS)
        p.add_argument("--keys"); p.add_argument("--note"); p.add_argument("--drift-free", action="store_true", help="skip concepts whose drift is undecided")
        p.set_defaults(fn=f)
    p = sp.add_parser("set"); p.add_argument("map"); p.add_argument("kind", choices=KINDS); p.add_argument("key"); p.add_argument("pairs", nargs="+"); p.set_defaults(fn=cmd_set)
    p = sp.add_parser("choose"); p.add_argument("map"); p.add_argument("concept"); p.add_argument("variant"); p.set_defaults(fn=cmd_choose)
    p = sp.add_parser("import"); p.add_argument("map"); p.add_argument("file"); p.set_defaults(fn=cmd_import)
    p = sp.add_parser("add-note"); p.add_argument("map"); p.add_argument("kind", choices=KINDS); p.add_argument("key"); p.add_argument("text"); p.set_defaults(fn=cmd_note)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
