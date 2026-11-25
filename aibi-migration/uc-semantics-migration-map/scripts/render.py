#!/usr/bin/env python3
"""render.py — semantic-map.yaml → ONE self-contained, interactive HTML assessment report.

The report is the review surface for the Assessment stage: browse the proposed Domains, Metric
Views, Pages and Wikis; rename things, fill in measure definitions, approve / reject; then
**Download decisions.json** and feed it back:  design.py … --decisions decisions.json

  render.py output/semantic-map.yaml -o output/report.html [--plan output/apply-plan.json]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from smlib import read_yaml, read_json, spec_hash, h12  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map")
    ap.add_argument("-o", "--out", default="output/report.html")
    ap.add_argument("--plan", default=None, help="apply-plan.json from `apply.py --plan-json` (embedded in the Apply tab)")
    a = ap.parse_args()

    m = read_yaml(a.map)
    for kind in ("domains", "concepts", "metric_views", "pages", "wikis", "asset_tags"):
        for o in m.get(kind, []):
            o["_stale"] = bool(o.get("approval") == "approved" and o.get("approved_hash") != spec_hash(kind, o))
    plan = read_json(a.plan, []) if a.plan and os.path.exists(a.plan) else []
    tpl = open(os.path.join(HERE, "..", "templates", "report_template.html"), encoding="utf-8").read()
    payload = json.dumps(dict(map=m, plan=plan, fingerprint=h12([m.get("meta"), [o["key"] for k in ("domains", "metric_views") for o in m.get(k, [])]])),
                         ensure_ascii=False, default=str).replace("</", "<\\/")
    html = tpl.replace("__TITLE__", (m["meta"].get("title") or "UC Semantics Migration Map").replace("<", "&lt;")).replace("__DATA__", payload)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(html)
    print(f"report → {a.out} ({len(html) // 1024} KB, self-contained)")


if __name__ == "__main__":
    main()
