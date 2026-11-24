#!/usr/bin/env python3
"""patterns.py — LIVE reference to databricks-solutions/uc-semantics-patterns.

That repo holds tested, best-practice Metric View YAML for recurring modelling problems (period-over-period,
YTD, moving windows, semi-additive balances, ranking, currency conversion, segmentation, fiscal/retail
calendars, ABC classification). The skill reads it at AUTHORING time so Metric Views follow current
guidance instead of whatever was true when this skill was written.

  patterns.py index [--refresh]        list patterns (live from GitHub; cached; offline snapshot as fallback)
  patterns.py show "<folder>" [--yml]  print a pattern's README (and its YAML with --yml)
  patterns.py match "<text>"           which patterns a concept name hints at

Resolution order for every read:  live GitHub  →  on-disk cache (output/.cache)  →  bundled snapshot
(references/patterns-index.snapshot.json — INDEX ONLY: folder names, summaries, file lists, the commit it
was taken from; never the YAML itself). So it works offline / behind a firewall, just less fresh, and always
says which source it used and which commit.

Stdlib only (urllib). Unauthenticated GitHub API (60 req/h) is plenty; set GITHUB_TOKEN to raise it.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "databricks-solutions/uc-semantics-patterns"
BRANCH = "main"
SNAPSHOT = os.path.join(HERE, "..", "references", "patterns-index.snapshot.json")
CACHE_DIR = os.environ.get("UCSM_CACHE", os.path.join(os.getcwd(), "output", ".cache"))

# concept-name → pattern folder. Folder names are the repo's own (checked against the live tree in `index`).
RULES = [
    (r"\b(yoy|y/y|year[- ]over[- ]year|mom|qoq|wow|growth|prior (year|period|month|quarter)|vs\.? (last|prior))\b",
     "Time Intelligence/Period-over-period growth"),
    (r"\b(ytd|qtd|mtd|period[- ]to[- ]date|to[- ]date)\b", "Time Intelligence/Period-to-date growth"),
    (r"\b(rolling|moving|trailing|ttm|t12m|l12m|\d+[- ]?(day|week|month)s?)\b", "Time Intelligence/Moving calculations"),
    (r"\b(on[- ]hand|inventory|stock|balance|opening|closing|snapshot|headcount|weeks of supply)\b", "Semi-additive calculations"),
    (r"\b(rank|top ?\d*|percentile|decile)\b", "Ranking"),
    (r"\b(currency|fx|exchange|usd|eur|gbp|converted|local amount)\b", "Currency conversion"),
    (r"\b(price band|band|bucket)\b", "Static segmentation"),
    (r"\b(segment|tier|cohort|loyalty)\b", "Dynamic segmentation"),
    (r"\b(fiscal)\b", "Calendars/Fiscal Calendar"),
    (r"\b(4-5-4|retail calendar|nrf)\b", "Calendars/Retail Calendar"),
    (r"\b(abc|pareto)\b", "ABC classification"),
]


def match(text):
    t = (text or "").lower()
    out = []
    for rx, folder in RULES:
        if re.search(rx, t) and folder not in out:
            out.append(folder)
    return out


def _get(url, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": "uc-semantics-migration-map", **({"Accept": accept} if accept else {})})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")


def raw(path, ref=BRANCH):
    return _get(f"https://raw.githubusercontent.com/{REPO}/{ref}/{urllib.parse.quote(path)}")


def _first_para(md):
    for ln in md.splitlines():
        t = ln.strip()
        if t and not t.startswith(("#", "!", "[!", "|", "---", "<", "```")):
            return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)[:300]
    return ""


def live_index():
    head = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"))["sha"]
    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/{head}?recursive=1"))["tree"]
    folders = {}
    for n in tree:
        if n["type"] != "blob":
            continue
        p = n["path"]
        d = os.path.dirname(p)
        if not d or d.endswith("images"):
            continue
        if p.lower().endswith((".yml", ".yaml", ".sql")) or p.endswith("README.md"):
            folders.setdefault(d, []).append(os.path.basename(p))
    pats = []
    for d, files in sorted(folders.items()):
        if not any(f.lower().endswith((".yml", ".yaml")) for f in files):
            continue
        try:
            summ = _first_para(raw(f"{d}/README.md", head)) if "README.md" in files else ""
        except Exception:
            summ = ""
        pats.append(dict(folder=d, files=sorted(files), summary=summ))
    return dict(repo=REPO, commit=head, source="live", patterns=pats)


def get_index(refresh=False):
    cache = os.path.join(CACHE_DIR, "patterns-index.json")
    if not refresh and os.path.exists(cache):
        try:
            d = json.load(open(cache))
            d["source"] = "cache"
            return d
        except Exception:
            pass
    try:
        d = live_index()
        os.makedirs(CACHE_DIR, exist_ok=True)
        json.dump(d, open(cache, "w"), indent=1)
        return d
    except Exception as e:
        if os.path.exists(cache):
            d = json.load(open(cache))
            d["source"] = f"cache (live failed: {type(e).__name__})"
            return d
        d = json.load(open(SNAPSHOT))
        d["source"] = f"bundled snapshot (live failed: {type(e).__name__}: {str(e)[:60]})"
        return d


def show(folder, with_yml):
    idx = get_index()
    pat = next((p for p in idx["patterns"] if p["folder"].lower() == folder.lower()), None)
    if not pat:
        sys.exit(f"unknown pattern '{folder}'. Known: " + "; ".join(p["folder"] for p in idx["patterns"]))
    print(f"# {pat['folder']}   [{idx['repo']} @ {idx['commit'][:8]} · index: {idx['source']}]\n")
    try:
        print(raw(f"{pat['folder']}/README.md", idx["commit"]))
        if with_yml:
            for f in pat["files"]:
                if f.lower().endswith((".yml", ".yaml")):
                    print(f"\n\n## {f}\n```yaml\n{raw(pat['folder'] + '/' + f, idx['commit'])}\n```")
    except Exception as e:
        print(f"(could not fetch pattern content: {type(e).__name__}. Browse: https://github.com/{REPO}/tree/{BRANCH}/"
              f"{urllib.parse.quote(pat['folder'])})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("index"); a.add_argument("--refresh", action="store_true"); a.add_argument("--json", action="store_true")
    b = sp.add_parser("show"); b.add_argument("folder"); b.add_argument("--yml", action="store_true")
    c = sp.add_parser("match"); c.add_argument("text")
    o = ap.parse_args()
    if o.cmd == "index":
        d = get_index(o.refresh)
        if o.json:
            print(json.dumps(d, indent=1))
        else:
            print(f"{d['repo']} @ {d['commit'][:8]}  (index source: {d['source']})")
            for p in d["patterns"]:
                print(f"- {p['folder']}: {p['summary'][:110]}")
    elif o.cmd == "show":
        show(o.folder, o.yml)
    else:
        print("\n".join(match(o.text)) or "(no pattern hint)")


if __name__ == "__main__":
    main()
