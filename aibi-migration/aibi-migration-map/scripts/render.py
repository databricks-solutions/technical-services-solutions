#!/usr/bin/env python3
"""
render.py — turn a curated mapping.yaml into ONE self-contained HTML report.

The report has two mirrored tabs:
  1. Migration Map   — workbook → Databricks asset, and the mirror asset → workbooks
  2. Metric View Blueprint — each Metric View as a concept + the reports feeding it

Output is a single file: all CSS/JS inline, no external references — safe to email/share.

Usage:
  python3 render.py mapping.yaml -o report.html
"""
import sys, os, re, html, argparse
try:
    import yaml
except ImportError:
    sys.exit("Needs pyyaml.  pip install pyyaml")

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "templates", "report_template.html")

def esc(s): return html.escape(str(s))
def slug(s): return "mv-" + re.sub(r"[^a-z0-9]+","-", str(s).lower()).strip("-")
KIND_LABEL = {"dashboard":"Dashboard","genie":"Genie","app":"App","alert":"SQL Alert","retire":"Retire"}
KORD = {"dashboard":0,"genie":1,"app":2,"alert":3}

def mvlink(mv_title):
    if not mv_title or mv_title == "—": return '<code>—</code>'
    return f'<a class="mvlink" href="#{slug(mv_title)}"><code>{esc(mv_title)}</code></a>'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mapping")
    ap.add_argument("-o","--out", default="report.html")
    args = ap.parse_args()
    M = yaml.safe_load(open(args.mapping))
    meta   = M.get("meta", {})
    groups = M.get("groups", {})
    mviews = M.get("metric_views", {})
    assets = M.get("assets", {})
    wbs    = M.get("workbooks", [])

    # resolve MV title for an asset id
    def asset_mv_title(aid):
        a = assets.get(aid, {})
        mv = a.get("metric_view")
        return mviews.get(mv, {}).get("title", "—") if mv else "—"

    # ---- Table 1: workbook rows grouped by subject group ----
    gorder = list(groups.keys())
    by = {g: [] for g in gorder}
    for w in wbs:
        by.setdefault(w.get("group","?"), []).append(w)
        if w.get("group") not in gorder: gorder.append(w.get("group"))
    t1 = []
    for g in gorder:
        grp = by.get(g, [])
        if not grp: continue
        t1.append(f'<tr class="grouphdr"><td colspan="5"><span class="gletter">{esc(str(g)[:2])}</span> '
                  f'{esc(groups.get(g,g))} <span class="gcount">{len(grp)} workbooks</span></td></tr>')
        for w in sorted(grp, key=lambda x:-int(x.get("worksheets",0))):
            tgt = w.get("target","")
            retire = tgt == "RETIRE"
            kind = "retire" if retire else assets.get(tgt,{}).get("kind","dashboard")
            if retire:
                surv = w.get("survivor","")
                tname = f'Duplicate → folds into {esc(assets.get(surv,{}).get("name", surv))}'
                mv_title = "—"
            else:
                tname = esc(assets.get(tgt,{}).get("name", tgt))
                mv_title = asset_mv_title(tgt)
            t1.append(
              f'<tr data-kind="{kind}" data-name="{esc(w["name"]).lower()}">'
              f'<td class="wbcell"><code>{esc(w["name"])}</code><span class="folder">{esc(groups.get(g,g))}</span></td>'
              f'<td class="num">{int(w.get("worksheets",0))}</td>'
              f'<td><span class="src">{esc(w.get("source","—"))}</span></td>'
              f'<td class="tgtcell"><span class="chip chip-{kind}">{KIND_LABEL[kind]}</span><span class="tgtname">{tname}</span></td>'
              f'<td class="mvcell">{mvlink(mv_title)}</td></tr>')
    TABLE1 = "\n".join(t1)

    # ---- Table 2: asset rows (mirror) ----
    asset_wbs = {}
    for w in wbs:
        if w.get("target") == "RETIRE": continue
        asset_wbs.setdefault(w["target"], []).append(w)
    t2 = []
    for aid in sorted(asset_wbs, key=lambda k:(KORD.get(assets.get(k,{}).get("kind","dashboard"),9), k)):
        a = assets.get(aid, {}); rs = asset_wbs[aid]
        kind = a.get("kind","dashboard")
        mv = a.get("metric_view"); mvo = mviews.get(mv, {}) if mv else {}
        mv_title = mvo.get("title","—"); mvsrc = mvo.get("core_source","—")
        ws = sum(int(x.get("worksheets",0)) for x in rs)
        names = " · ".join(f'<code>{esc(x["name"])}</code>' for x in sorted(rs, key=lambda y:-int(y.get("worksheets",0))))
        t2.append(
          f'<tr data-kind="{kind}" data-names="{esc(" ".join(x["name"] for x in rs)).lower()}">'
          f'<td class="assetcell"><span class="chip chip-{kind}">{KIND_LABEL[kind]}</span>'
          f'<span class="assetname">{esc(a.get("name",aid))}</span><code class="assetid">{esc(aid)}</code></td>'
          f'<td class="num">{len(rs)}</td><td class="num">{ws}</td>'
          f'<td class="mvcell">{mvlink(mv_title)}<span class="mvsrc">{esc(mvsrc)}</span></td>'
          f'<td class="wblist">{names}</td></tr>')
    TABLE2 = "\n".join(t2)

    # ---- MV cards ----
    # attach reports (live + retired-that-fold-into-this-MV) to each MV
    mv_reports = {k: [] for k in mviews}
    surv_mv = {}
    for aid, a in assets.items():
        surv_mv[aid] = a.get("metric_view")
    for w in wbs:
        if w.get("target") == "RETIRE":
            mv = surv_mv.get(w.get("survivor"))
            retired = True
        else:
            mv = surv_mv.get(w.get("target"))
            retired = False
        if mv and mv in mv_reports:
            mv_reports[mv].append(dict(name=w["name"],
                                       ws=int(w.get("worksheets",0)), retired=retired))
    cards = []
    for mvid, m in mviews.items():
        reps = sorted(mv_reports.get(mvid, []), key=lambda x:(x["retired"], -x["ws"]))
        n = len(reps); ws = sum(r["ws"] for r in reps)
        load = '<span class="loadtag">Load-bearing</span>' if m.get("load_bearing") else ''
        metrics = "".join(f"<li>{esc(x)}</li>" for x in m.get("metrics",[]))
        drift = m.get("drift",[])
        if drift:
            drows = "".join(f'<div class="drow"><code>{esc(d[0])}</code><span>{esc(d[1])}</span></div>' for d in drift)
            drift_block = f'<div class="sub-h">Drift to resolve</div><div class="drift">{drows}</div>'
        else: drift_block = ''
        shared = m.get("shared",[])
        shared_block = ('<div class="sub-h">Shared logic to fold in</div><ul class="tight">'
                        + "".join(f"<li>{esc(x)}</li>" for x in shared) + '</ul>') if shared else ''
        repchips = ""
        for r in reps:
            cls = "rep rep-retire" if r["retired"] else "rep"
            tag = '<span class="rtag">folds in</span>' if r["retired"] else ''
            repchips += (f'<span class="{cls}" title="{r["ws"]} sheets">'
                         f'<code>{esc(r["name"])}</code>{tag}</span>')
        cards.append(f'''
    <article id="{slug(m.get("title",mvid))}" class="mv" data-name="{esc(m.get("title",mvid)).lower()} {' '.join(esc(r['name']).lower() for r in reps)}">
      <header class="mv-h"><div class="mv-title"><h2>{esc(m.get("title",mvid))}</h2><code class="mvid">{esc(mvid)}</code>{load}</div>
        <div class="mv-count"><span class="big">{n}</span><span class="lbl">reports</span><span class="ws">{ws} sheets</span></div></header>
      <p class="purpose">{esc(m.get("purpose",""))}</p>
      <div class="mv-body">
        <div class="col"><div class="sub-h">Metrics it standardizes</div><ul class="tight">{metrics}</ul>
          <div class="sub-h">Grain</div><p class="meta">{esc(m.get("grain","—"))}</p>
          <div class="sub-h">Time dimension</div><p class="meta">{esc(m.get("time_dimension", m.get("time","—")))}</p></div>
        <div class="col">{drift_block}{shared_block}
          <div class="sub-h">Owner needed</div><p class="meta owner">{esc(m.get("owner","—"))}</p></div></div>
      <div class="reports"><div class="sub-h">Reports to consider when building it <span class="rhint">(“folds in” = duplicate absorbed)</span></div>
        <div class="repwrap">{repchips}</div></div>
    </article>''')
    CARDS = "\n".join(cards)

    # ---- stats ----
    n_wb = len(wbs)
    n_retire = sum(1 for w in wbs if w.get("target")=="RETIRE")
    ws_retire = sum(int(w.get("worksheets",0)) for w in wbs if w.get("target")=="RETIRE")
    kinds = {}
    for aid in asset_wbs:
        k = assets.get(aid,{}).get("kind","dashboard"); kinds[k] = kinds.get(k,0)+1
    n_mv = sum(1 for k in mviews if mv_reports.get(k))

    # ---- assumptions + why + eyebrow ----
    assumptions = "".join(
        f'<div class="a"><b>{esc(a.get("label",""))}</b><span>{esc(a.get("text",""))}</span></div>'
        for a in meta.get("assumptions",[]))
    eyebrow = esc(meta.get("account","")) + (f' · {esc(meta["engagement"])}' if meta.get("engagement") else "") + " · AI/BI Migration"
    source_note = esc(meta.get("source_note", "Generated by the aibi-migration-map skill."))
    tool = meta.get("source_tool", "Tableau")
    units = "reports" if tool == "Power BI" else "workbooks"
    unit_sing = "report" if tool == "Power BI" else "workbook"

    tpl = open(TEMPLATE).read()
    rep = {
      "{{TITLE}}": esc(meta.get("title","Tableau → Databricks Migration Map")),
      "{{SOURCETOOL}}": esc(tool), "{{UNITS}}": units, "{{UNIT_SING}}": unit_sing,
      "{{EYEBROW}}": eyebrow, "{{SUBTITLE}}": esc(meta.get("subtitle","")),
      "{{ASSUMPTIONS}}": assumptions, "{{WHY}}": meta.get("why",""),
      "{{SOURCE_NOTE}}": source_note,
      "{{NWB}}": str(n_wb), "{{NASSETS}}": str(sum(kinds.values())),
      "{{NDASH}}": str(kinds.get("dashboard",0)), "{{NGENIE}}": str(kinds.get("genie",0)),
      "{{NAPP}}": str(kinds.get("app",0)), "{{NALERT}}": str(kinds.get("alert",0)),
      "{{NMV}}": str(n_mv), "{{NRETIRE}}": str(n_retire), "{{WSRETIRE}}": str(ws_retire),
      "{{TABLE1}}": TABLE1, "{{TABLE2}}": TABLE2, "{{CARDS}}": CARDS,
    }
    for k, v in rep.items():
        tpl = tpl.replace(k, v)
    open(args.out, "w").write(tpl)
    print(f"Rendered {args.out} ({len(tpl):,} bytes) — {n_wb} workbooks → {sum(kinds.values())} assets, "
          f"{n_mv} metric views, {n_retire} retired. Single self-contained file.")

if __name__ == "__main__":
    main()
