#!/usr/bin/env python3
"""apply.py — IMPLEMENTATION: semantic-map.yaml (approved objects) → Unity Catalog objects.

SAFE BY DEFAULT.  No flags = a read-only PLAN (live reads, zero writes).  Writing needs --execute.

  apply.py output/semantic-map.yaml                      # plan against the live workspace (read-only)
  apply.py output/semantic-map.yaml --offline            # plan without connecting (everything = create)
  apply.py output/semantic-map.yaml --execute --yes      # write (the agent must have the user's explicit go first)
  apply.py … --only metric_views,asset_tags              # restrict to some object kinds
  apply.py … --publish      domains/pages/wikis are created as DRAFT unless you pass this
  apply.py … --prune        also delete objects THIS TOOL created earlier that the map no longer wants
  apply.py … --adopt        take over a same-named object that exists but this tool did not create
  apply.py … --profile P    Databricks CLI profile (omit inside Genie Code / a notebook: auth is ambient)

Idempotent: every object is compared with its live state first; unchanged ⇒ `noop`, no write. Run twice and
the second plan is empty. Only objects whose approval hash still matches their current spec are touched, and a
Metric View additionally needs its authored YAML approved (author.py) — an edit after approval needs re-approval.

Order: governed tags → domains (parents first) → metric views → asset tags → pages → wikis.
A Metric View is first created under a throw-away name and every measure is queried; only if that passes is the
real view created/replaced — so a broken definition can never overwrite a good one.
"""
import argparse
import json
import os
import sys
import urllib.parse
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from smlib import read_yaml, read_json, write_json, spec_hash, spec_of, slug, h12, yaml_ok, MARKER  # noqa: E402
from dbx import DbxClient, ApiError, NotFound, Unsupported, Denied  # noqa: E402

DOMAINS = "/api/2.0/domains"
TAGPOL = "/api/2.1/tag-policies"
PAGES = "/api/2.0/knowledge/pages"
WIKI = "/api/2.0/knowledge/tables/{fqn}/page"
TABLES = "/api/2.1/unity-catalog/tables/{fqn}"
GENERAL = "system.general_domain"
ORDER = ["tag_policies", "domains", "metric_views", "asset_tags", "pages", "wikis"]
UUID_NS = uuid.UUID("6f1a2b3c-4d5e-4f60-8a7b-9c0d1e2f3a4b")


def request_id(key):
    """Deterministic UUIDv4-formatted id (the API insists on v4): same key ⇒ same id ⇒ retries cannot duplicate."""
    return str(uuid.UUID(int=uuid.uuid5(UUID_NS, key).int, version=4))

NEEDS = {
    "tag_policies": "Permission to create governed tags (account admin)",
    "domains": "MANAGE DISCOVER (account level) — account admins and workspace admins hold it by default",
    "metric_views": "USE CATALOG + USE SCHEMA + CREATE TABLE on the target schema; SELECT on each source table; "
                    "CAN USE on a SQL warehouse running DBR 17.3+",
    "asset_tags": "APPLY TAG on each tagged table + ASSIGN permission on the governed tag; USE CATALOG/SCHEMA",
    "pages": "MANAGE PAGES (default: all account users) — or MANAGE DOMAIN / MANAGE DISCOVER to publish",
    "wikis": "Write access on each documented table (wikis are Beta, one per table)",
}


def paged(c, path, key, params=None, limit=200):
    """Follow next_page_token to the end — list APIs may return a short page AND a token."""
    out, params = [], dict(params or {})
    for _ in range(limit):
        r = c.get(path, params)
        out += r.get(key, [])
        tok = r.get("next_page_token")
        if not tok:
            break
        params["page_token"] = tok
    return out


def quote_sql(s):
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def mv_sql(fqn, yaml_text):
    return f"CREATE OR REPLACE VIEW {fqn} WITH METRICS LANGUAGE YAML AS $$\n{yaml_text.strip()}\n$$"


def mv_measures(yaml_text):
    import yaml
    d = yaml.safe_load(yaml_text) or {}
    return [m["name"] for m in (d.get("measures") or []) if isinstance(m, dict) and m.get("name")]


def same_yaml(a, b):
    import yaml
    try:
        return yaml.safe_load(a) == yaml.safe_load(b)
    except Exception:
        return False


def eligible(kind, o, opts):
    if o.get("status") == "orphaned":
        return False, "orphaned (input disappeared) — kept, not applied"
    if o.get("approval") == "rejected":
        return False, "rejected"
    if o.get("blockers"):
        return False, "blocked: " + "; ".join(o["blockers"])
    if not opts.include_unapproved:
        if o.get("approval") != "approved":
            return False, "not approved"
        if o.get("approved_hash") != spec_hash(kind, o):
            return False, "changed since approval — re-approve"
    if kind == "metric_views":
        if not o.get("yaml"):
            return False, "YAML not authored yet (Stage 2a: author.py)"
        if not opts.include_unapproved and not yaml_ok(o):
            return False, "authored YAML not approved (author.py approve) or changed since approval"
    return True, ""


class Plan:
    def __init__(self):
        self.ops = []
        self.caps = {}

    def add(self, **kw):
        self.ops.append(kw)
        return kw


def key_owned(st, key):
    return key in st and bool(st[key].get("applied"))


# ------------------------------------------------------------------ planning
def plan_all(m, c, state, opts):  # noqa: C901
    P = Plan()
    st = state.setdefault("objects", {})
    live, caps = {}, P.caps
    only = set(opts.only.split(",")) if getattr(opts, "only", None) else None
    want_kind = (lambda k: only is None or k in only)

    def probe(name, fn):
        if opts.offline:
            caps[name] = True
            return
        try:
            live[name] = fn()
            caps[name] = True
        except Unsupported:
            caps[name] = False
        except NotFound:
            caps[name] = True
            live[name] = None
        except Denied as e:
            caps[name] = False
            P.add(kind=name, key="*", action="unavailable", reason=f"permission denied: {str(e)[:120]}")
        except ApiError as e:
            caps[name] = False
            P.add(kind=name, key="*", action="unavailable", reason=f"preflight failed: {str(e)[:140]}")

    probe("domains", lambda: paged(c, DOMAINS, "domains"))
    probe("tag_policies", lambda: paged(c, TAGPOL, "tag_policies"))
    live_domains = {d["tag_key"]: d for d in (live.get("domains") or [])}
    live_tags = {t.get("tag_key") for t in (live.get("tag_policies") or [])}
    domains = {d["key"]: d for d in m["domains"]}
    dom_status, dom_id = {}, {}   # key -> ok|skip ; key -> live domain_id (None until created)
    ids_known = {}
    for d in m["domains"]:
        cur = live_domains.get(d["tag_key"])
        dom_id[d["key"]] = cur["domain_id"] if cur else None

    # ---- governed tags + domains (parents first)
    def depth(d):
        n = 0
        while d.get("parent"):
            d = domains.get(d["parent"], {})
            n += 1
        return n

    for d in sorted(m["domains"], key=lambda x: (depth(x), x["key"])):
        if not want_kind("domains"):
            dom_status[d["key"]] = "ok" if dom_id[d["key"]] else "skip"
            continue
        ok, why = eligible("domains", d, opts)
        if ok and d.get("parent") and dom_status.get(d["parent"]) != "ok":
            ok, why = False, "parent domain not applied"
        if not ok:
            dom_status[d["key"]] = "skip"
            P.add(kind="domains", key=d["key"], action="skip", reason=why, name=d["name"])
            continue
        dom_status[d["key"]] = "ok"
        h = spec_hash("domains", d)
        if caps.get("tag_policies") is False:
            P.add(kind="tag_policies", key=f"tag:{d['tag_key']}", action="manual",
                  reason=f"governed tag `{d['tag_key']}` must exist — create it in the account console (API unavailable)")
        elif opts.offline or d["tag_key"] not in live_tags:
            P.add(kind="tag_policies", key=f"tag:{d['tag_key']}", action="create", tag_key=d["tag_key"],
                  name=d["tag_key"], reason="governed tag backing the domain")
        elif not key_owned(st, f"tag:{d['tag_key']}"):
            P.add(kind="tag_policies", key=f"tag:{d['tag_key']}", action="noop", name=d["tag_key"],
                  reason="governed tag already exists (NOT created by this tool) — the domain will reuse it; "
                         "set target.tag_prefix to namespace in a shared account")
        if caps.get("domains") is False:
            P.add(kind="domains", key=d["key"], action="manual", reason="domains API unavailable", name=d["name"])
            continue
        cur = live_domains.get(d["tag_key"])
        want = dict(subtitle=d.get("subtitle"), description=d.get("description"))
        if cur is None:
            P.add(kind="domains", key=d["key"], action="create", name=d["name"], hash=h, tag_key=d["tag_key"],
                  parent=d.get("parent"), body=want, domain_id=f"ucsm-{slug(d['key'])}"[:60].replace("_", "-"),
                  reason="no domain on this tag" + ("" if opts.publish else " (created as DRAFT)"))
        else:
            if d.get("parent") and cur.get("parent_domain_id") != dom_id.get(d["parent"]) and dom_id.get(d["parent"]):
                P.add(kind="domains", key=d["key"], action="block", name=d["name"],
                      reason="parent is immutable — delete + recreate by hand if the hierarchy really changed")
                continue
            if key_owned(st, d["key"]) or opts.adopt:
                diff = {k: v for k, v in want.items() if v and cur.get(k) != v}
                if opts.publish and cur.get("effective_draft"):
                    diff["draft"] = False
                if diff:
                    P.add(kind="domains", key=d["key"], action="update", name=d["name"], hash=h,
                          domain_id=cur["domain_id"], body=diff, reason="fields differ: " + ", ".join(diff))
                else:
                    P.add(kind="domains", key=d["key"], action="noop", name=d["name"], hash=h,
                          domain_id=cur["domain_id"], reason="in sync")
            else:
                P.add(kind="domains", key=d["key"], action="block", name=d["name"],
                      reason=f"a domain on tag `{d['tag_key']}` already exists and was not created by this tool — use --adopt")

    # ---- metric views
    for mv in sorted(m["metric_views"], key=lambda x: x["key"]):
        if not want_kind("metric_views"):
            continue
        ok, why = eligible("metric_views", mv, opts)
        if ok and mv["domain"] not in dom_status:
            ok, why = False, "domain missing"
        if not ok:
            P.add(kind="metric_views", key=mv["key"], action="skip", reason=why, name=mv["fqn"])
            continue
        y = mv["yaml"]
        if "$$" in y:
            P.add(kind="metric_views", key=mv["key"], action="block", reason="'$$' inside the YAML breaks the DDL quoting", name=mv["fqn"])
            continue
        h = h12(y)
        exists = None
        if not opts.offline:
            try:
                exists = c.get(TABLES.format(fqn=mv["fqn"]))
            except NotFound:
                exists = None
            except ApiError as e:
                P.add(kind="metric_views", key=mv["key"], action="block", reason=str(e)[:140], name=mv["fqn"])
                continue
        if exists is None:
            P.add(kind="metric_views", key=mv["key"], action="create", name=mv["fqn"], hash=h, yaml=y, reason="does not exist")
        else:
            # trust what we recorded applying; otherwise fall back to comparing the live definition's content
            live_def = exists.get("view_definition") or exists.get("definition")
            in_sync = (st.get(mv["key"]) or {}).get("hash") == h or bool(live_def and same_yaml(live_def, y))
            if in_sync:
                P.add(kind="metric_views", key=mv["key"], action="noop", name=mv["fqn"], hash=h, reason="in sync")
            elif key_owned(st, mv["key"]) or opts.adopt:
                P.add(kind="metric_views", key=mv["key"], action="update", name=mv["fqn"], hash=h, yaml=y, reason="definition changed")
            else:
                P.add(kind="metric_views", key=mv["key"], action="block", name=mv["fqn"],
                      reason="object exists but was not created by this tool — use --adopt to take it over")

    # ---- asset tags (domain membership)
    replaced = {o["name"] for o in P.ops if o["kind"] == "metric_views" and o["action"] in ("create", "update")}
    for a in sorted(m["asset_tags"], key=lambda x: x["key"]):
        if not want_kind("asset_tags"):
            continue
        ok, why = eligible("asset_tags", a, opts)
        if ok and dom_status.get(a.get("domain")) != "ok":
            ok, why = False, "domain not applied"
        label = f"{a['name']} ← {a['tag_key']}"
        if not ok:
            P.add(kind="asset_tags", key=a["key"], action="skip", reason=why, name=label)
            continue
        h = spec_hash("asset_tags", a)
        have = None
        if not opts.offline:
            try:
                cat, sch, tb = a["name"].split(".")
                rows = c.sql(f"SELECT tag_name FROM {cat}.information_schema.table_tags WHERE table_name = '{tb}' AND schema_name = '{sch}'")
                have = a["tag_key"] in [r[0] for r in rows]
            except (ApiError, ValueError):
                have = None
        if a["name"] in replaced:
            have = False  # CREATE OR REPLACE VIEW drops the view's tags — put them back
        if have:
            P.add(kind="asset_tags", key=a["key"], action="noop", name=label, hash=h, reason="tag present")
        else:
            val = f" = '{quote_sql(a['tag_value'])}'" if a.get("tag_value") else ""
            P.add(kind="asset_tags", key=a["key"], action="create", name=label, hash=h,
                  sql=f"ALTER {'VIEW' if '.mv_' in a['name'] else 'TABLE'} {a['name']} SET TAGS ('{quote_sql(a['tag_key'])}'{val})",
                  reason="tag missing" if a["name"] not in replaced else "view (re)created — tag re-applied")

    # ---- pages
    gen_id = (live_domains.get(GENERAL) or {}).get("domain_id")
    for p in sorted(m["pages"], key=lambda x: x["key"]):
        if not want_kind("pages"):
            continue
        ok, why = eligible("pages", p, opts)
        if ok and p["domain"] != "general" and dom_status.get(p["domain"]) != "ok":
            ok, why = False, "domain not applied"
        if not ok:
            P.add(kind="pages", key=p["key"], action="skip", reason=why, name=p["title"])
            continue
        h = spec_hash("pages", p)
        if caps.get("pages") is False:
            P.add(kind="pages", key=p["key"], action="export", name=p["title"], hash=h,
                  reason="Pages API unavailable → exported as markdown for Genie Code bulk import / manual create")
            continue
        did = gen_id if p["domain"] == "general" else dom_id.get(p["domain"])
        want = dict(display_name=p["title"], body=p.get("body") or "", description=(p.get("description") or "")[:1000],
                    synonyms=sorted(p.get("synonyms") or []))
        cur = None
        if did and not opts.offline:
            try:
                lst = paged(c, PAGES, "pages", {"filter": f'domain = "domains/{did}"', "page_size": 100})
                hit = next((x for x in lst if x.get("display_name") == p["title"] and x.get("domain") == f"domains/{did}"), None)
                cur = c.get(f"/api/2.0/knowledge/{hit['name']}") if hit else None
            except Unsupported:
                caps["pages"] = False
                P.add(kind="pages", key=p["key"], action="export", name=p["title"], hash=h, reason="Pages API unavailable → exported as markdown")
                continue
            except ApiError as e:
                P.add(kind="pages", key=p["key"], action="block", name=p["title"], reason=str(e)[:140])
                continue
        if p["domain"] == "general" and not did and not opts.offline:
            P.add(kind="pages", key=p["key"], action="block", name=p["title"], reason="default General domain not found")
            continue
        if cur is None:
            P.add(kind="pages", key=p["key"], action="create", name=p["title"], hash=h, domain_key=p["domain"], domain_id=did, body=want,
                  request_id=request_id(p["key"]), reason="does not exist" + ("" if opts.publish else " (created as DRAFT)"))
        else:
            diff = {k: v for k, v in want.items() if k != "display_name" and (cur.get(k) or ([] if k == "synonyms" else "")) != v}
            if opts.publish and cur.get("state") != "PUBLISHED":
                diff["state"] = "PUBLISHED"
            if diff and (key_owned(st, p["key"]) or opts.adopt):
                P.add(kind="pages", key=p["key"], action="update", name=p["title"], hash=h, page=cur["name"], body=diff,
                      reason="fields differ: " + ", ".join(diff))
            elif diff:
                P.add(kind="pages", key=p["key"], action="block", name=p["title"],
                      reason="a page with this title exists in the domain but was not created by this tool — use --adopt")
            else:
                P.add(kind="pages", key=p["key"], action="noop", name=p["title"], hash=h, page=cur["name"], reason="in sync")

    # ---- wikis
    for w in sorted(m["wikis"], key=lambda x: x["key"]):
        if not want_kind("wikis"):
            continue
        ok, why = eligible("wikis", w, opts)
        if not ok:
            P.add(kind="wikis", key=w["key"], action="skip", reason=why, name=w["table"])
            continue
        h = spec_hash("wikis", w)
        path = WIKI.format(fqn=w["table"])
        cur = None
        if not opts.offline:
            try:
                cur = c.get(path)
            except NotFound:
                cur = None
            except Unsupported:
                P.add(kind="wikis", key=w["key"], action="export", name=w["table"], hash=h, reason="Wikis API unavailable → exported as markdown")
                continue
            except ApiError as e:
                P.add(kind="wikis", key=w["key"], action="block", name=w["table"], reason=str(e)[:140])
                continue
        if cur is None:
            P.add(kind="wikis", key=w["key"], action="create", name=w["table"], hash=h, path=path, body=dict(body=w["body"]),
                  reason="no wiki yet" + ("" if opts.publish else " (DRAFT)"))
        elif ((cur.get("body") or "") == w["body"] or (st.get(w["key"]) or {}).get("hash") == h) \
                and not (opts.publish and cur.get("state") != "PUBLISHED"):
            P.add(kind="wikis", key=w["key"], action="noop", name=w["table"], hash=h, reason="in sync")
        elif key_owned(st, w["key"]) or opts.adopt:
            P.add(kind="wikis", key=w["key"], action="update", name=w["table"], hash=h, path=path, body=dict(body=w["body"]), reason="content changed")
        else:
            P.add(kind="wikis", key=w["key"], action="block", name=w["table"],
                  reason="a wiki already exists on this table and was not written by this tool — use --adopt")

    if opts.prune:
        wanted = {o["key"] for o in P.ops if o["action"] in ("create", "update", "noop")}
        for key, rec in sorted(st.items()):
            if key not in wanted and rec.get("kind") in ("domains", "metric_views", "pages", "tag_policies"):
                P.add(kind=rec["kind"], key=key, action="prune", name=rec.get("name", key), reason="no longer in the approved map", remote=rec)
    return P


# ------------------------------------------------------------------ execution
def validate_mv(c, fqn, y, key):
    """Create under a throw-away name, query every measure, drop it. Raises ApiError with the first failure."""
    cat, sch, _ = fqn.split(".")
    tmp = f"{cat}.{sch}.__ucsm_check_{h12([key, y])[:8]}"
    try:
        c.sql(mv_sql(tmp, y))
        bad = []
        for name in mv_measures(y):
            try:
                c.sql(f"SELECT MEASURE(`{name}`) FROM {tmp}")
            except ApiError as e:
                bad.append(f"{name}: {str(e)[:160]}")
        if bad:
            raise ApiError("measure(s) failed to evaluate — " + " | ".join(bad[:4]))
    finally:
        try:
            c.sql(f"DROP VIEW IF EXISTS {tmp}")
        except ApiError:
            pass


def execute(P, c, state, opts, state_path):  # noqa: C901
    st = state.setdefault("objects", {})
    results, dom_ids = [], {}

    def record(o, remote=None):
        st[o["key"]] = dict(kind=o["kind"], hash=o.get("hash"), name=o.get("name"), applied=True, remote=remote)
        write_json(state_path, state)

    for o in P.ops:  # domain ids known from the plan (live) so dependents can resolve
        if o["kind"] == "domains" and o.get("domain_id"):
            dom_ids[o["key"]] = o["domain_id"]

    order = {k: i for i, k in enumerate(ORDER)}
    # build forward; tear down in reverse (pages → domains → views → tags)
    for o in sorted(P.ops, key=lambda o: (1, -order.get(o["kind"], 99)) if o["action"] == "prune" else (0, order.get(o["kind"], 99))):
        a, k = o["action"], o["kind"]
        try:
            if a == "create" and k == "tag_policies":
                try:
                    c.post(TAGPOL, dict(tag_key=o["tag_key"], description=f"Domain tag ({MARKER})"))
                except ApiError as e:
                    if "already exists" not in str(e).lower():
                        raise
                record(o)
            elif a == "create" and k == "domains":
                body = dict(tag_key=o["tag_key"], draft=not opts.publish, **{x: v for x, v in o["body"].items() if v})
                if o.get("parent"):
                    body["parent_domain_id"] = dom_ids.get(o["parent"]) or o["parent"]
                r = c.post(DOMAINS, body, params=dict(domain_id=o["domain_id"]))
                dom_ids[o["key"]] = r.get("domain_id", o["domain_id"])
                record(o, dom_ids[o["key"]])
            elif a == "update" and k == "domains":
                c.patch(f"{DOMAINS}/{o['domain_id']}", o["body"], params=dict(update_mask=",".join(o["body"])))
                record(o, o["domain_id"])
            elif a in ("create", "update") and k == "metric_views":
                if not opts.no_verify:
                    validate_mv(c, o["name"], o["yaml"], o["key"])
                c.sql(mv_sql(o["name"], o["yaml"]))
                record(o)
            elif a in ("create", "update") and k == "asset_tags":
                c.sql(o["sql"])
                st[o["key"]] = dict(kind="asset_tags", hash=o["hash"], name=o["name"], applied=True)
                write_json(state_path, state)
            elif a == "create" and k == "pages":
                did = o.get("domain_id") or dom_ids.get(o["domain_key"])
                if not did:
                    raise ApiError("domain id unknown — its domain was not created in this run")
                body = dict(o["body"], domain=f"domains/{did}", state="PUBLISHED" if opts.publish else "DRAFT")
                r = c.post(PAGES, body, params=dict(request_id=o["request_id"]))
                record(o, r.get("name"))
            elif a == "update" and k == "pages":
                body = dict(o["body"])
                c.patch(f"/api/2.0/knowledge/{o['page']}", body, params=dict(update_mask=",".join(body)))
                record(o, o["page"])
            elif a in ("create", "update") and k == "wikis":
                body = dict(o["body"], **({"state": "PUBLISHED"} if opts.publish else ({} if a == "update" else {"state": "DRAFT"})))
                c.patch(o["path"], body, params=dict(update_mask=",".join(body)))
                record(o)
            elif a == "prune":
                r = o["remote"]
                if k == "metric_views":
                    c.sql(f"DROP VIEW IF EXISTS {r['name']}")
                elif k == "domains":
                    c.delete(f"{DOMAINS}/{r['remote']}")
                elif k == "tag_policies":
                    c.delete(f"{TAGPOL}/{urllib.parse.quote(r['name'], safe='')}")
                else:
                    c.delete(f"/api/2.0/knowledge/{r['remote']}")
                st.pop(o["key"], None)
                write_json(state_path, state)
            elif a == "noop" and o["key"] not in st and k in ("domains", "metric_views", "pages", "wikis") and opts.adopt:
                record(o, o.get("domain_id") or o.get("page"))
            results.append((o, "ok"))
        except ApiError as e:
            results.append((o, f"ERROR {str(e)[:300]}"))
            print(f"  ✗ {k}/{o['key']}: {str(e)[:300]}", file=sys.stderr)
    return results


def export_fallbacks(m, P, outdir):
    n = 0
    for o in P.ops:
        if o["action"] != "export":
            continue
        src = next(x for x in m[o["kind"]] if x["key"] == o["key"])
        d = os.path.join(outdir, "export", o["kind"])
        os.makedirs(d, exist_ok=True)
        head = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in
                                    [("title", src.get("title") or src.get("table")), ("domain", src.get("domain")),
                                     ("synonyms", src.get("synonyms") or []), ("description", src.get("description") or "")]) + "\n---\n\n"
        with open(os.path.join(d, slug(o["key"]) + ".md"), "w", encoding="utf-8") as f:
            f.write(head + (src.get("body") or ""))
        n += 1
    return n


def print_plan(P, opts):
    from collections import Counter
    cnt = Counter(o["action"] for o in P.ops)
    icon = dict(create="+", update="~", noop="=", skip="·", block="✗", export="⇪", manual="☞", prune="−", unavailable="?")
    print(f"\n{'PLAN (offline)' if opts.offline else 'PLAN (live reads, no writes)'}")
    for k in ORDER:
        rows = [o for o in P.ops if o["kind"] == k]
        if not rows:
            continue
        print(f"\n[{k}]  needs: {NEEDS[k]}")
        for o in rows:
            print(f"  {icon.get(o['action'], '?')} {o['action']:<6} {str(o.get('name', o['key'])):<52} {o['reason']}")
    s = {a: cnt.get(a, 0) for a in ("create", "update", "noop", "skip", "block", "export", "manual", "prune")}
    print("\nsummary:", ", ".join(f"{k}={v}" for k, v in s.items() if v))
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map")
    ap.add_argument("--state", default=None, help="apply-state.json (default: next to the map)")
    ap.add_argument("--profile", default=None, help="Databricks CLI profile (omit inside Databricks: ambient auth)")
    ap.add_argument("--warehouse-id", default=None)
    ap.add_argument("--only", default=None, help="comma list of kinds: tag_policies,domains,metric_views,asset_tags,pages,wikis")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--adopt", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="skip the validate-then-create check of metric views (not recommended)")
    ap.add_argument("--include-unapproved", action="store_true", help="sandbox only: treat `proposed` as approved")
    ap.add_argument("--fake", action="store_true", help="use the in-memory FakeClient (demo/tests)")
    ap.add_argument("--plan-json", default=None, help="write the plan here (the HTML report embeds it)")
    o = ap.parse_args()

    m = read_yaml(o.map)
    outdir = os.path.dirname(os.path.abspath(o.map))
    state_path = o.state or os.path.join(outdir, "apply-state.json")
    state = read_json(state_path, {"schema": 1, "objects": {}})

    if o.fake:
        from dbx import FakeClient
        c = FakeClient()
    else:
        c = DbxClient(o.profile, o.warehouse_id or (m["meta"].get("target") or {}).get("warehouse_id"))

    P = plan_all(m, c, state, o)
    s = print_plan(P, o)
    if o.plan_json:
        write_json(o.plan_json, [{k: v for k, v in op.items() if k not in ("sql", "body", "remote", "yaml")} for op in P.ops])
    n = export_fallbacks(m, P, outdir)
    if n:
        print(f"exported {n} object(s) as markdown → {outdir}/export/")

    if not o.execute:
        print("\nDry run — nothing was written. Re-run with --execute (after reviewing the plan) to apply.")
        return
    writes = sum(s.get(k, 0) for k in ("create", "update", "prune"))
    if not writes:
        print("\nNothing to write — already in sync.")
        return
    if not o.yes:
        if not sys.stdin.isatty():
            sys.exit("--execute needs --yes when not run from a terminal (confirm with the user first).")
        if input(f"\nApply {writes} change(s) as {c.who()}? type 'apply' to continue: ").strip() != "apply":
            sys.exit("aborted")
    res = execute(P, c, state, o, state_path)
    bad = [r for r in res if r[1] != "ok"]
    print(f"\napplied: {len(res) - len(bad)} ok, {len(bad)} failed. State → {state_path}")
    if any(op["kind"] in ("domains", "pages", "wikis") and op["action"] == "create" for op in P.ops) and not o.publish:
        print("Domains/Pages/Wikis were created as DRAFTS. A curator publishes them in Discover, or re-run with --publish.")
    print("Manual steps the API cannot do: domain display names & Discover-page sections — see references/uc-objects.md.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
