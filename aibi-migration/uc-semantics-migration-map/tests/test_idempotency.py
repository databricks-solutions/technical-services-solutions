#!/usr/bin/env python3
"""End-to-end contract test — no workspace needed (uses dbx.FakeClient). Exercises the real CLIs.

  python3 -I tests/test_idempotency.py        (from the skill root)

Asserts what the skill promises:
  1. design.py twice on the same inputs ⇒ byte-identical map; hand edits are auto-pinned
  2. Assessment writes NO metric-view YAML (concepts + shells only)
  3. a Metric View needs shell approval AND authored+approved YAML before apply touches it
  4. apply twice ⇒ second plan has ZERO create/update and the client sees ZERO writes
  5. a drift decision changed after authoring ⇒ the YAML is STALE and apply skips it until re-authored
  6. a broken metric view can never replace a good one (validate-then-create)
  7. input disappears ⇒ orphaned, NOT deleted, unless --prune
  8. Pages/Wikis API missing ⇒ graceful export fallback
  9. nothing approved ⇒ nothing written
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
sys.path.insert(0, S)
import apply as A  # noqa: E402
from dbx import FakeClient, ApiError  # noqa: E402
from smlib import read_yaml, write_yaml, read_json  # noqa: E402

EX = os.path.join(ROOT, "examples")
T = None
MAP = STATE = None
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def fresh_dir():
    global T, MAP, STATE
    if T:
        shutil.rmtree(T, ignore_errors=True)
    T = tempfile.mkdtemp(prefix="ucsm-")
    MAP, STATE = os.path.join(T, "semantic-map.yaml"), os.path.join(T, "apply-state.json")


def sh(script, *args, ok=True):
    p = subprocess.run([sys.executable, "-I", os.path.join(S, script), *args], capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise SystemExit(f"{script} {args} failed:\n{p.stdout}\n{p.stderr}")
    return p


def design(inv=None, decisions=None):
    a = [inv or os.path.join(EX, "inventory.example.json"), "-o", MAP, "--config", os.path.join(EX, "design.example.yaml")]
    if decisions:
        a += ["--decisions", decisions]
    sh("design.py", *a)


def author_all(only=None):
    """Play the agent: write YAML for each shell from its concepts, register (static checks), approve."""
    m = read_yaml(MAP)
    cons = {c["key"]: c for c in m["concepts"]}
    for mv in m["metric_views"]:
        if only and mv["key"] != only:
            continue
        ms = []
        for k in mv["concepts"]:
            c = cons[k]
            ms.append(f"  - name: {c['name']}\n    expr: SUM(source.{c['name'].lower().replace(' ', '_')})\n    comment: {c['name']}")
        y = f"version: 1.1\ncomment: test\nsource: {mv['source_table']}\nmeasures:\n" + "\n".join(ms) + "\n"
        f = os.path.join(T, mv["key"] + ".yaml")
        open(f, "w").write(y)
        sh("author.py", "--offline", "register", MAP, mv["key"], f)
        sh("author.py", "--offline", "approve", MAP, mv["key"])


def approve_everything():
    m = read_yaml(MAP)
    for c in m["concepts"]:
        if c["drift"] and not c.get("chosen"):
            sh("decide.py", "choose", MAP, c["key"], "1")
    sh("decide.py", "approve", MAP, "--all")
    author_all()


def opts(**kw):
    d = dict(offline=False, publish=False, prune=False, adopt=False, include_unapproved=False, only=None, no_verify=False)
    d.update(kw)
    return argparse.Namespace(**d)


def run_apply(client, **kw):
    o = opts(**kw)
    m = read_yaml(MAP)
    state = read_json(STATE, {"schema": 1, "objects": {}})
    P = A.plan_all(m, client, state, o)
    res = A.execute(P, client, state, o, STATE)
    return P, res


def count(P, *actions):
    return sum(1 for o in P.ops if o["action"] in actions)


# ===== 1/2. determinism + no YAML in the Assessment
fresh_dir()
design()
a = open(MAP).read()
design()
check("design is byte-identical on re-run", a == open(MAP).read())
m = read_yaml(MAP)
check("Assessment defines concepts + shells, no metric-view YAML",
      len(m["concepts"]) >= 3 and all(not mv.get("yaml") for mv in m["metric_views"]) and not any("measures" in mv for mv in m["metric_views"]))
check("drift detected on concepts (and Tableau≡DAX syntax is not drift)",
      {c["name"] for c in m["concepts"] if c["drift"]} >= {"Net Revenue"} and not next(c for c in m["concepts"] if c["name"] == "On Hand")["drift"])
check("concepts carry pattern hints from the patterns repo", any(c["patterns"] for c in m["concepts"]))

# ===== 3. two-gate approval
sh("decide.py", "approve", MAP, "--all")
P0, _ = run_apply(FakeClient())
mv_skips = [o for o in P0.ops if o["kind"] == "metric_views"]
check("shell approved but YAML not authored ⇒ metric views skipped", mv_skips and all(o["action"] == "skip" and "YAML" in o["reason"] for o in mv_skips),
      str([(o["key"], o["reason"]) for o in mv_skips]))
author_all()
m = read_yaml(MAP)
check("authored + approved YAML marks authoring=approved", all(mv["authoring"] == "approved" for mv in m["metric_views"]))

# ===== 4. apply twice
c = FakeClient()
P1, r1 = run_apply(c)
check("first apply creates things", count(P1, "create") > 0, str(count(P1, "create")))
check("first apply has no errors", all(s == "ok" for _, s in r1), str([x for x in r1 if x[1] != "ok"][:2]))
check("domains created as draft by default", all(d["effective_draft"] for d in c.domains.values()))
check("no throw-away validation views left behind", not any("__ucsm_check" in k for k in c.tables))
w1 = len(c.writes)
P2, _ = run_apply(c)
check("second plan has 0 create/update/prune", count(P2, "create", "update", "prune") == 0,
      str([(o["kind"], o["action"], o["key"]) for o in P2.ops if o["action"] in ("create", "update")][:5]))
check("second apply performed 0 writes", len(c.writes) == w1, f"{len(c.writes) - w1} extra writes")
design()
P3, _ = run_apply(c)
check("design refresh after apply keeps apply a no-op", count(P3, "create", "update") == 0 and len(c.writes) == w1)

# ===== 5. stale YAML after a drift decision changes
m = read_yaml(MAP)
drift = next(c_ for c_ in m["concepts"] if c_["drift"])
sh("decide.py", "choose", MAP, drift["key"], "2")
m = read_yaml(MAP)
mvk = drift["mv"]
mv = next(x for x in m["metric_views"] if x["key"] == mvk)
check("changing a drift decision marks the authored YAML STALE", mv["authoring"].startswith("STALE"), mv["authoring"])
P4, _ = run_apply(c)
sk = [o for o in P4.ops if o["kind"] == "metric_views" and o["key"] == mvk]
check("apply skips the stale metric view (shell approval also invalidated)", sk and sk[0]["action"] == "skip", str(sk))
sh("decide.py", "approve", MAP, "--kind", "metric_views", "--keys", mvk)
sh("decide.py", "approve", MAP, "--kind", "concepts", "--keys", drift["key"])
f = os.path.join(T, "v2.yaml")
y = mv["yaml"].replace("SUM(source.", "SUM(0 + source.", 1)
open(f, "w").write(y)
sh("author.py", "--offline", "register", MAP, mvk, f)
sh("author.py", "--offline", "approve", MAP, mvk)
P5, _ = run_apply(c)
ch = [o for o in P5.ops if o["action"] in ("create", "update")]
check("after re-authoring + re-approval only that metric view (and its re-applied tags) change",
      [o["key"] for o in ch if o["kind"] == "metric_views"] == [mvk] and all(o["kind"] in ("metric_views", "asset_tags") for o in ch)
      and all(mv["fqn"] in o["name"] for o in ch if o["kind"] == "asset_tags"), str([(o["kind"], o["key"]) for o in ch]))

# ===== 6. a broken definition never replaces a good one
good = c.tables[mv["fqn"]]["view_definition"]
m = read_yaml(MAP)
mv = next(x for x in m["metric_views"] if x["key"] == mvk)
f = os.path.join(T, "bad.yaml")
open(f, "w").write(mv["yaml"].replace("SUM(", "BROKEN_FN(", 1))
sh("author.py", "--offline", "register", MAP, mvk, f)
sh("author.py", "--offline", "approve", MAP, mvk)
P6, r6 = run_apply(c)
check("broken metric view reported as an error", any(o["key"] == mvk and s != "ok" for o, s in r6), str([(o["key"], s) for o, s in r6 if s != "ok"]))
check("…the live (good) definition was NOT replaced", c.tables[mv["fqn"]]["view_definition"] == good)
check("…and no throw-away view leaked", not any("__ucsm_check" in k for k in c.tables))

# ===== 7. orphans + prune
fresh_dir()
design()
approve_everything()
c = FakeClient()
run_apply(c)
inv = read_json(os.path.join(EX, "inventory.example.json"))
inv["reports"] = [r for r in inv["reports"] if r["name"] not in ("Inventory Planning", "Stock Health")]
ip = os.path.join(T, "inv2.json")
json.dump(inv, open(ip, "w"))
design(inv=ip)
m = read_yaml(MAP)
orph = [x["key"] for k in ("domains", "concepts", "metric_views", "pages", "wikis", "asset_tags") for x in m[k] if x.get("status") == "orphaned"]
check("vanished reports orphan their objects", len(orph) >= 4, str(orph))
nd = len(c.domains)
run_apply(c)
check("orphans are NOT deleted by a normal apply", len(c.domains) == nd)
Pp, _ = run_apply(c, prune=True)
check("--prune removes only what we created and no longer want", count(Pp, "prune") >= 1 and len(c.domains) < nd, f"{count(Pp, 'prune')} pruned")

# ===== 8. missing Pages/Wikis API
fresh_dir()
design()
approve_everything()
c2 = FakeClient(pages=False, wikis=False)
P8, r8 = run_apply(c2)
check("no Pages/Wikis API ⇒ exported, run still succeeds", count(P8, "export") > 0 and all(s == "ok" for _, s in r8))
check("MVs + domains still applied", len(c2.domains) > 0 and any(t.get("table_type") == "METRIC_VIEW" for t in c2.tables.values()))

# ===== 9. nothing approved ⇒ nothing written
fresh_dir()
design()
c3 = FakeClient()
P9, _ = run_apply(c3)
check("nothing approved ⇒ nothing written", len(c3.writes) == 0 and count(P9, "create", "update") == 0)

# ===== 1b. hand edit in the yaml survives refresh (auto-pin)
fresh_dir()
design()
m = read_yaml(MAP)
m["domains"][0]["description"] = "HAND WRITTEN by the data steward"
m["metric_views"][0]["purpose"] = "Steward-authored purpose"
write_yaml(MAP, m)
design()
m = read_yaml(MAP)
check("hand-edited domain description survives refresh", m["domains"][0]["description"] == "HAND WRITTEN by the data steward")
check("hand-edited MV purpose survives refresh", m["metric_views"][0]["purpose"] == "Steward-authored purpose")
check("…and is recorded in pinned", "description" in m["domains"][0]["pinned"])
a = open(MAP).read()
design()
check("refresh with pins is still byte-stable", a == open(MAP).read())

shutil.rmtree(T, ignore_errors=True)
print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
