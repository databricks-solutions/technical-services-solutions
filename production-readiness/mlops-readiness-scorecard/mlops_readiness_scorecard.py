# Databricks notebook source
# MAGIC %md
# MAGIC # 🧭 MLOps Readiness Scorecard
# MAGIC
# MAGIC A **read-only** self-assessment you run inside *your own* Databricks workspace.
# MAGIC It inspects how you're actually doing ML today and grades it against Databricks
# MAGIC MLOps best practices — **before** you commit to a workflow.
# MAGIC
# MAGIC ### How to use
# MAGIC 1. Attach to any cluster or serverless (uses only pre-installed `mlflow` + `databricks-sdk`).
# MAGIC 2. **Run All**.
# MAGIC 3. Read the scorecard at the bottom — each check is 🟢 / 🟡 / 🔴 with *why it matters* and *how to fix*.
# MAGIC
# MAGIC ### What it checks
# MAGIC | Area | Practices |
# MAGIC |---|---|
# MAGIC | **Tracking** | Experiments logged · autologging · params/metrics · model signatures |
# MAGIC | **Model management** | Registered to **Unity Catalog** (not legacy registry) · **aliases** vs. deprecated stages · versions documented |
# MAGIC | **Serving & monitoring** | Model Serving endpoints · inference tables · Lakehouse Monitoring |
# MAGIC | **Engineering discipline** | Git (Repos) · CI/CD via Asset Bundles · dev/staging/prod separation · Feature Engineering in UC |
# MAGIC
# MAGIC > 100% read-only. It **lists and reads** metadata only — it never creates, edits, or deletes anything.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0 · Dependencies
# MAGIC Pre-installed on Databricks Runtime **ML** (no-op there). On serverless / plain
# MAGIC runtimes this self-installs `mlflow` + `databricks-sdk`, then restarts Python.

# COMMAND ----------

import importlib.util, subprocess, sys

# mlflow-skinny carries the tracking/registry client + model metadata APIs we use,
# and installs far faster than full mlflow on serverless.
_need = [pkg for pkg, mod in [("mlflow-skinny", "mlflow"), ("databricks-sdk", "databricks.sdk")]
         if importlib.util.find_spec(mod) is None]
if _need:
    print(f"Installing {_need} …")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *_need])
    dbutils.library.restartPython()  # reload interpreter so imports below pick up the installs
else:
    print("mlflow + databricks-sdk already available — no install needed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Configuration

# COMMAND ----------

dbutils.widgets.text("catalog_scope", "", "Catalog to scope UC checks to (blank = all accessible)")
dbutils.widgets.text("max_models_sampled", "50", "Max registered models to inspect")
dbutils.widgets.text("signature_sample", "8", "How many models to deep-check for signatures (slower)")
dbutils.widgets.dropdown("check_serving", "true", ["true", "false"], "Check serving endpoints")

CATALOG_SCOPE = (dbutils.widgets.get("catalog_scope") or "").strip()
MAX_MODELS = int(dbutils.widgets.get("max_models_sampled") or "50")
SIG_SAMPLE = int(dbutils.widgets.get("signature_sample") or "8")
CHECK_SERVING = dbutils.widgets.get("check_serving") == "true"

print(f"catalog_scope   = {CATALOG_SCOPE or '(all)'}")
print(f"max_models      = {MAX_MODELS}")
print(f"signature_sample= {SIG_SAMPLE}")
print(f"check_serving   = {CHECK_SERVING}")

# COMMAND ----------

import mlflow
import itertools
from mlflow.tracking import MlflowClient
from dataclasses import dataclass, field
from typing import Optional

# Bound how much we pull from potentially huge workspaces (keeps runtime predictable).
LIST_CAP = 300

def capped(iterable, n=LIST_CAP):
    return list(itertools.islice(iterable, n))

# Workspace (legacy) registry + UC registry clients.
ws_reg = MlflowClient(registry_uri="databricks")       # legacy Workspace Model Registry
uc_reg = MlflowClient(registry_uri="databricks-uc")    # Unity Catalog registry
tracking = MlflowClient()                              # experiment tracking

try:
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    SDK_OK = True
except Exception as e:  # pragma: no cover
    w = None
    SDK_OK = False
    print(f"⚠️  databricks-sdk unavailable ({e}); SDK-based checks will be skipped.")

GREEN, YELLOW, RED, SKIP = "GREEN", "YELLOW", "RED", "SKIP"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Check framework
# MAGIC Each check returns a status, one-line detail, *why it matters*, and *how to fix*.

# COMMAND ----------

@dataclass
class Check:
    area: str
    title: str
    status: str = SKIP
    detail: str = ""
    why: str = ""
    fix: str = ""

RESULTS: list[Check] = []

def record(area, title, status, detail, why="", fix=""):
    RESULTS.append(Check(area, title, status, detail, why, fix))
    icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "SKIP": "⚪"}[status]
    print(f"{icon} [{area}] {title} — {detail}")

def safe(fn, default=None):
    """Run a probe, swallow failures so one broken API can't sink the scorecard."""
    try:
        return fn()
    except Exception as e:
        return ("__ERR__", str(e)) if default is None else default

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Tracking & experiments

# COMMAND ----------

# One bounded pass: list a capped set of experiments, then sample runs across them
# in a SINGLE search_runs call (avoids one API round-trip per experiment).
def check_tracking():
    exps = safe(lambda: list(tracking.search_experiments(max_results=200)), default=None)
    if not isinstance(exps, list):
        record("Tracking", "Experiments logged", SKIP, "could not list experiments")
        record("Tracking", "Params / metrics / autolog", SKIP, "experiments unavailable")
        return
    if not exps:
        record("Tracking", "Experiments logged", RED, "no experiments found",
               why="Untracked training means no reproducibility, comparison, or lineage.",
               fix="Wrap training in `with mlflow.start_run():` or enable autologging.")
        record("Tracking", "Params / metrics / autolog", SKIP, "no experiments to sample")
        return

    exp_ids = [e.experiment_id for e in exps[:25]]
    runs = safe(lambda: list(tracking.search_runs(exp_ids, max_results=100)), default=[])
    runs = runs if isinstance(runs, list) else []
    if not runs:
        record("Tracking", "Experiments logged", RED,
               f"{len(exps)} experiment(s) but no runs in the sampled set",
               why="Empty experiments mean training isn't actually being tracked.",
               fix="Log training with `mlflow.start_run()` / `mlflow.autolog()`.")
        record("Tracking", "Params / metrics / autolog", SKIP, "no runs sampled")
        return

    record("Tracking", "Experiments logged", GREEN,
           f"{len(exps)} experiment(s); {len(runs)} run(s) sampled",
           why="Logged runs give you comparison, reproducibility, and model lineage.")

    sampled = len(runs)
    autolog_hits = sum(1 for r in runs if any(k.startswith("mlflow.autologging") for k in (r.data.tags or {})))
    rich_runs = sum(1 for r in runs if r.data.params and r.data.metrics)
    pct = rich_runs / sampled
    autolog_note = f" · autolog on {autolog_hits}/{sampled}" if autolog_hits else ""
    if pct >= 0.7:
        record("Tracking", "Params / metrics / autolog", GREEN,
               f"{rich_runs}/{sampled} sampled runs log both params & metrics{autolog_note}",
               why="Params+metrics per run are the minimum for comparison & governance.")
    elif pct > 0:
        record("Tracking", "Params / metrics / autolog", YELLOW,
               f"only {rich_runs}/{sampled} sampled runs log both params & metrics",
               why="Sparse logging makes runs hard to compare or reproduce.",
               fix="Turn on `mlflow.autolog()` so params, metrics & artifacts are captured automatically.")
    else:
        record("Tracking", "Params / metrics / autolog", RED,
               f"0/{sampled} sampled runs log params & metrics",
               why="Runs without params/metrics can't be compared or audited.",
               fix="Enable `mlflow.autolog()` at the top of training.")

check_tracking()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Model management (Unity Catalog)

# COMMAND ----------

def _list_uc_models():
    filt = f"catalog='{CATALOG_SCOPE}'" if CATALOG_SCOPE else None
    raw = list(uc_reg.search_registered_models(filter_string=filt, max_results=MAX_MODELS)) \
        if filt else list(uc_reg.search_registered_models(max_results=MAX_MODELS))
    # Exclude Databricks-provided models (system.ai.* foundation models, internal
    # catalogs) — they aren't the customer's work and would skew every count.
    return [m for m in raw if not m.name.startswith(("system.", "__databricks"))]

def _list_legacy_models():
    return list(ws_reg.search_registered_models(max_results=MAX_MODELS))

uc_models = safe(_list_uc_models, default=[])
legacy_models = safe(_list_legacy_models, default=[])
uc_err = isinstance(uc_models, tuple)
lg_err = isinstance(legacy_models, tuple)
uc_models = [] if uc_err else uc_models
legacy_models = [] if lg_err else legacy_models

# --- Registered to Unity Catalog vs legacy ------------------------------------
if uc_err and not uc_models:
    record("Model mgmt", "Models in Unity Catalog", SKIP,
           "UC registry not accessible from this workspace")
elif len(uc_models) == 0 and len(legacy_models) > 0:
    record("Model mgmt", "Models in Unity Catalog", RED,
           f"0 UC models, but {len(legacy_models)} in the legacy Workspace Registry",
           why="The Workspace Model Registry is deprecated — no UC governance, lineage, or cross-workspace access.",
           fix="Register with a 3-level name: `mlflow.set_registry_uri('databricks-uc')` then `registered_model_name='catalog.schema.model'`.")
elif len(uc_models) > 0 and len(legacy_models) > 0:
    record("Model mgmt", "Models in Unity Catalog", YELLOW,
           f"{len(uc_models)} in UC, but still {len(legacy_models)} in the legacy registry",
           why="Split registries fragment governance and lineage.",
           fix="Migrate remaining legacy models to UC and point all training at `databricks-uc`.")
elif len(uc_models) > 0:
    record("Model mgmt", "Models in Unity Catalog", GREEN,
           f"{len(uc_models)} model(s) registered to Unity Catalog",
           why="UC gives you governance, lineage, and cross-workspace model access.")
else:
    record("Model mgmt", "Models in Unity Catalog", RED,
           "no registered models found in UC or legacy registry",
           why="Unregistered models can't be governed, versioned, aliased, or served cleanly.",
           fix="Register your best run: `mlflow.register_model(run_uri, 'catalog.schema.model')`.")

# --- Aliases (Champion/Challenger) vs deprecated stages ------------------------
def check_aliases():
    if not uc_models:
        record("Model mgmt", "Aliases (Champion/Challenger)", SKIP, "no UC models to inspect")
        return
    with_alias = 0
    sample = uc_models[:MAX_MODELS]
    for m in sample:
        rm = safe(lambda: uc_reg.get_registered_model(m.name), default=None)
        aliases = getattr(rm, "aliases", None) if rm and not isinstance(rm, tuple) else None
        if aliases:
            with_alias += 1
    if with_alias == 0:
        record("Model mgmt", "Aliases (Champion/Challenger)", RED,
               f"0/{len(sample)} UC models use aliases",
               why="Aliases are how UC promotes models (stages are deprecated). Without them, serving/deployment can't reference 'the current prod model'.",
               fix="Set an alias: `client.set_registered_model_alias('catalog.schema.model', 'Champion', version)` and serve `models:/…@Champion`.")
    elif with_alias < len(sample):
        record("Model mgmt", "Aliases (Champion/Challenger)", YELLOW,
               f"{with_alias}/{len(sample)} UC models use aliases",
               why="Inconsistent alias use means some models can't be promoted/served by reference.",
               fix="Adopt a consistent alias convention (e.g. Champion/Challenger) across all production models.")
    else:
        record("Model mgmt", "Aliases (Champion/Challenger)", GREEN,
               f"{with_alias}/{len(sample)} UC models use aliases")

check_aliases()

# --- Still using deprecated stages? -------------------------------------------
def check_legacy_stages():
    if not legacy_models:
        record("Model mgmt", "No deprecated stages", GREEN if uc_models else SKIP,
               "no legacy-registry models found" if uc_models else "legacy registry empty/inaccessible")
        return
    staged = 0
    for m in legacy_models[:MAX_MODELS]:
        mvs = safe(lambda: ws_reg.search_model_versions(f"name='{m.name}'"), default=[])
        if isinstance(mvs, list):
            for mv in mvs:
                if getattr(mv, "current_stage", None) in ("Staging", "Production"):
                    staged += 1
    if staged > 0:
        record("Model mgmt", "No deprecated stages", RED,
               f"{staged} model version(s) still using Staging/Production stages",
               why="MLflow stages are deprecated in favor of UC aliases.",
               fix="Move to UC + aliases; stages won't be supported long-term.")
    else:
        record("Model mgmt", "No deprecated stages", YELLOW,
               "legacy models exist but none use stages",
               why="Legacy-registry models should still migrate to UC.",
               fix="Migrate remaining legacy models to Unity Catalog.")

check_legacy_stages()

# --- Versions documented (description/tags) -----------------------------------
def check_docs():
    if not uc_models:
        record("Model mgmt", "Models documented", SKIP, "no UC models to inspect")
        return
    documented = 0
    sample = uc_models[:MAX_MODELS]
    for m in sample:
        if getattr(m, "description", None):
            documented += 1
    pct = documented / len(sample)
    if pct >= 0.7:
        record("Model mgmt", "Models documented", GREEN,
               f"{documented}/{len(sample)} models have descriptions")
    elif pct > 0:
        record("Model mgmt", "Models documented", YELLOW,
               f"only {documented}/{len(sample)} models have descriptions",
               why="Undocumented models are hard to govern and hand over.",
               fix="Add descriptions/tags on registered models and versions.")
    else:
        record("Model mgmt", "Models documented", RED,
               f"0/{len(sample)} models have descriptions",
               why="No descriptions = no context for reviewers, auditors, or teammates.",
               fix="Set `client.update_registered_model(name, description=...)` and tag versions.")

check_docs()

# --- Model signatures (deep check, sampled) -----------------------------------
def check_signatures():
    if not uc_models:
        record("Model mgmt", "Model signatures", SKIP, "no UC models to inspect")
        return
    sample = uc_models[:SIG_SAMPLE]
    checked, with_sig = 0, 0
    for m in sample:
        mvs = safe(lambda: uc_reg.search_model_versions(f"name='{m.name}'"), default=[])
        if not isinstance(mvs, list) or not mvs:
            continue
        latest = sorted(mvs, key=lambda v: int(v.version))[-1]
        info = safe(lambda: mlflow.models.get_model_info(f"models:/{m.name}/{latest.version}"), default=None)
        if info is None or isinstance(info, tuple):
            continue
        checked += 1
        if getattr(info, "signature", None) is not None:
            with_sig += 1
    if checked == 0:
        record("Model mgmt", "Model signatures", SKIP, "could not load any model artifacts to check")
        return
    if with_sig == checked:
        record("Model mgmt", "Model signatures", GREEN,
               f"{with_sig}/{checked} sampled models have a signature")
    elif with_sig > 0:
        record("Model mgmt", "Model signatures", YELLOW,
               f"only {with_sig}/{checked} sampled models have a signature",
               why="Signatures enable schema validation & are required for many serving paths.",
               fix="Log with `signature=infer_signature(X, y)` and an `input_example`.")
    else:
        record("Model mgmt", "Model signatures", RED,
               f"0/{checked} sampled models have a signature",
               why="No signature = no input/output schema, brittle serving, no validation.",
               fix="Add `signature=infer_signature(...)` + `input_example=...` when logging models.")

check_signatures()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Serving & monitoring

# COMMAND ----------

def check_serving_and_monitoring():
    if not (SDK_OK and CHECK_SERVING):
        record("Serving", "Model Serving endpoints", SKIP, "serving check disabled or SDK unavailable")
        return
    eps = safe(lambda: capped(w.serving_endpoints.list(), 100), default=[])
    if isinstance(eps, tuple):
        record("Serving", "Model Serving endpoints", SKIP, f"could not list endpoints: {eps[1]}")
        return
    if not eps:
        record("Serving", "Model Serving endpoints", YELLOW,
               "no serving endpoints found",
               why="Not every use case needs real-time serving — but production ML usually does.",
               fix="If you need real-time/batch scoring, deploy a Model Serving endpoint from a UC model.")
        record("Serving", "Inference tables", SKIP, "no endpoints to inspect")
        return
    record("Serving", "Model Serving endpoints", GREEN, f"{len(eps)} endpoint(s) deployed")

    # Inference tables (payload logging) — sampled deep check.
    inf_on = 0
    checked = 0
    for ep in eps[:15]:
        full = safe(lambda: w.serving_endpoints.get(ep.name), default=None)
        if full is None or isinstance(full, tuple):
            continue
        checked += 1
        cfg = getattr(full, "config", None)
        acc = getattr(cfg, "auto_capture_config", None) if cfg else None
        # Inference tables live in two places depending on endpoint type:
        # classic custom-model serving (config.auto_capture_config) and
        # AI-Gateway / FM endpoints (ai_gateway.inference_table_config).
        gw = getattr(full, "ai_gateway", None)
        itc = getattr(gw, "inference_table_config", None) if gw else None
        if (acc and getattr(acc, "enabled", False)) or (itc and getattr(itc, "enabled", False)):
            inf_on += 1
    if checked == 0:
        record("Serving", "Inference tables", SKIP, "could not inspect endpoint configs")
    elif inf_on == checked:
        record("Serving", "Inference tables", GREEN, f"{inf_on}/{checked} endpoints log inference tables")
    elif inf_on > 0:
        record("Serving", "Inference tables", YELLOW,
               f"only {inf_on}/{checked} endpoints log inference tables",
               why="Inference tables are the foundation for monitoring & drift detection.",
               fix="Enable inference tables (auto-capture) on all production endpoints.")
    else:
        record("Serving", "Inference tables", RED,
               f"0/{checked} endpoints log inference tables",
               why="Without payload logging you can't monitor quality or detect drift in production.",
               fix="Enable inference tables on each endpoint's config (auto_capture_config).")

check_serving_and_monitoring()

# --- Lakehouse Monitoring (best-effort) ---------------------------------------
def check_monitoring():
    if not SDK_OK:
        record("Serving", "Lakehouse Monitoring", SKIP, "SDK unavailable")
        return
    qm = getattr(w, "quality_monitors", None) or getattr(w, "lakehouse_monitors", None)
    if qm is None or not hasattr(qm, "list"):
        record("Serving", "Lakehouse Monitoring", SKIP,
               "can't enumerate monitors from this SDK version",
               why="Lakehouse Monitoring tracks drift & quality on tables/inference logs.",
               fix="Create monitors on inference tables to track drift and quality over time.")
        return
    mons = safe(lambda: list(qm.list()), default=[])
    if isinstance(mons, tuple) or not mons:
        record("Serving", "Lakehouse Monitoring", YELLOW,
               "no Lakehouse monitors detected",
               why="Monitoring closes the MLOps loop — you catch drift/quality regressions before users do.",
               fix="Add a Lakehouse Monitor on your inference table(s).")
    else:
        record("Serving", "Lakehouse Monitoring", GREEN, f"{len(mons)} monitor(s) configured")

check_monitoring()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Engineering discipline

# COMMAND ----------

# --- Git-backed code (Repos) --------------------------------------------------
def check_repos():
    if not SDK_OK:
        record("Engineering", "Git-backed code (Repos)", SKIP, "SDK unavailable")
        return
    repos = safe(lambda: capped(w.repos.list()), default=[])
    if isinstance(repos, tuple):
        record("Engineering", "Git-backed code (Repos)", SKIP, f"could not list repos: {repos[1]}")
    elif repos:
        record("Engineering", "Git-backed code (Repos)", GREEN, f"{len(repos)} Git repo(s) in workspace")
    else:
        record("Engineering", "Git-backed code (Repos)", RED,
               "no Git repos found",
               why="Notebooks-only work has no version control, review, or CI/CD hook.",
               fix="Connect a Git provider and work from Databricks Repos / Git folders.")

check_repos()

# --- CI/CD via Asset Bundles --------------------------------------------------
def check_bundles():
    if not SDK_OK:
        record("Engineering", "CI/CD (Asset Bundles)", SKIP, "SDK unavailable")
        return
    jobs = safe(lambda: capped(w.jobs.list(expand_tasks=False)), default=[])
    if isinstance(jobs, tuple):
        record("Engineering", "CI/CD (Asset Bundles)", SKIP, f"could not list jobs: {jobs[1]}")
        return
    bundle_jobs = 0
    for j in jobs[:500]:
        st = getattr(j, "settings", None)
        dep = getattr(st, "deployment", None) if st else None
        kind = getattr(dep, "kind", None)
        if kind and "BUNDLE" in str(kind).upper():
            bundle_jobs += 1
    if bundle_jobs > 0:
        record("Engineering", "CI/CD (Asset Bundles)", GREEN,
               f"{bundle_jobs} job(s) deployed via Asset Bundles")
    elif jobs:
        record("Engineering", "CI/CD (Asset Bundles)", YELLOW,
               f"{len(jobs)} job(s) found, none deployed via Asset Bundles",
               why="Bundles (DABs) give you code-defined, environment-promotable, CI/CD-friendly deployments.",
               fix="Move jobs/pipelines into a Databricks Asset Bundle and deploy per environment.")
    else:
        record("Engineering", "CI/CD (Asset Bundles)", RED,
               "no jobs found; no evidence of automated deployment",
               why="Manual, click-ops deployment doesn't scale and isn't reproducible.",
               fix="Adopt Databricks Asset Bundles for jobs, pipelines, and model deployment.")

check_bundles()

# --- dev / staging / prod separation ------------------------------------------
def check_env_separation():
    if not SDK_OK:
        record("Engineering", "Environment separation", SKIP, "SDK unavailable")
        return
    cats = safe(lambda: [c.name.lower() for c in capped(w.catalogs.list(), 500)], default=[])
    if isinstance(cats, tuple):
        record("Engineering", "Environment separation", SKIP, f"could not list catalogs: {cats[1]}")
        return
    def tier(name):
        # Order matters: check nonprod/preprod before the bare 'prod' substring.
        if "nonprod" in name or "preprod" in name: return "nonprod"
        if "dev" in name: return "dev"
        if "stag" in name: return "staging"
        if "test" in name or "qa" in name: return "test"
        if "prod" in name: return "prod"
        return None
    tiers = {t for t in (tier(c) for c in cats) if t}
    if len(tiers) >= 2:
        record("Engineering", "Environment separation", GREEN,
               f"catalogs span multiple environment tiers: {sorted(tiers)}")
    elif tiers:
        record("Engineering", "Environment separation", YELLOW,
               f"only one environment tier detected: {sorted(tiers)}",
               why="Promoting models dev→staging→prod needs isolated environments.",
               fix="Adopt catalog-per-environment (e.g. dev/staging/prod) or workspace separation.")
    else:
        record("Engineering", "Environment separation", YELLOW,
               "no dev/staging/prod naming detected among catalogs",
               why="Without isolation, experiments and prod share blast radius.",
               fix="Separate environments via catalogs (dev/staging/prod) and promote across them.")

check_env_separation()

# --- Feature Engineering in UC (best-effort, needs catalog_scope) -------------
def check_feature_tables():
    if not CATALOG_SCOPE:
        record("Engineering", "Feature Engineering in UC", SKIP,
               "set the catalog_scope widget to enable this check")
        return
    try:
        df = spark.sql(f"""
            SELECT COUNT(*) AS pk_tables
            FROM {CATALOG_SCOPE}.information_schema.table_constraints
            WHERE constraint_type = 'PRIMARY KEY'
        """)
        n = df.collect()[0]["pk_tables"]
    except Exception as e:
        record("Engineering", "Feature Engineering in UC", SKIP, f"could not query information_schema: {e}")
        return
    if n and n > 0:
        record("Engineering", "Feature Engineering in UC", GREEN,
               f"{n} primary-key (feature-ready) table(s) in '{CATALOG_SCOPE}'",
               why="PK-constrained UC tables can back Feature Engineering / online lookups.")
    else:
        record("Engineering", "Feature Engineering in UC", YELLOW,
               f"no primary-key tables found in '{CATALOG_SCOPE}'",
               why="Feature tables need a primary key to be used by Feature Engineering / serving.",
               fix="Define feature tables in UC with primary keys and use the Feature Engineering client.")

check_feature_tables()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7 · 🏁 Scorecard

# COMMAND ----------

WEIGHT = {GREEN: 1.0, YELLOW: 0.5, RED: 0.0}
scored = [c for c in RESULTS if c.status in WEIGHT]
pct = (sum(WEIGHT[c.status] for c in scored) / len(scored) * 100) if scored else 0.0

def stage(p):
    if p >= 90: return ("Optimized", "#1a7f37")
    if p >= 75: return ("Automated", "#2da44e")
    if p >= 50: return ("Managed",   "#bf8700")
    if p >= 25: return ("Repeatable","#d1651a")
    return ("Ad hoc", "#cf222e")

stage_name, stage_color = stage(pct)
n_green = sum(c.status == GREEN for c in RESULTS)
n_yellow = sum(c.status == YELLOW for c in RESULTS)
n_red = sum(c.status == RED for c in RESULTS)
n_skip = sum(c.status == SKIP for c in RESULTS)

BADGE = {GREEN: ("🟢", "#2da44e"), YELLOW: ("🟡", "#bf8700"),
         RED: ("🔴", "#cf222e"), SKIP: ("⚪", "#8b949e")}

areas = {}
for c in RESULTS:
    areas.setdefault(c.area, []).append(c)

rows = ""
for area, checks in areas.items():
    a_scored = [c for c in checks if c.status in WEIGHT]
    a_pct = (sum(WEIGHT[c.status] for c in a_scored) / len(a_scored) * 100) if a_scored else 0
    rows += f"""<tr style="background:#f6f8fa"><td colspan="2" style="padding:10px 12px;font-weight:700;
             border-top:2px solid #d0d7de">{area} · {a_pct:.0f}%</td></tr>"""
    for c in checks:
        icon, col = BADGE[c.status]
        detail = c.detail
        extra = ""
        if c.status in (YELLOW, RED) and (c.why or c.fix):
            extra = (f'<div style="color:#57606a;font-size:12px;margin-top:4px">'
                     f'{("<b>Why:</b> " + c.why + "<br>") if c.why else ""}'
                     f'{("<b>Fix:</b> " + c.fix) if c.fix else ""}</div>')
        rows += f"""<tr>
            <td style="padding:8px 12px;white-space:nowrap;border-top:1px solid #eaeef2;vertical-align:top">
                <span style="color:{col};font-weight:700">{icon} {c.title}</span></td>
            <td style="padding:8px 12px;border-top:1px solid #eaeef2">{detail}{extra}</td>
        </tr>"""

html = f"""
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:960px;color:#1f2328">
  <div style="border:1px solid #d0d7de;border-radius:12px;overflow:hidden">
    <div style="padding:20px 24px;background:linear-gradient(90deg,{stage_color}22,transparent)">
      <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#57606a">MLOps Readiness</div>
      <div style="font-size:34px;font-weight:800;line-height:1.1;margin-top:4px">{pct:.0f}%
        <span style="font-size:20px;font-weight:700;color:{stage_color}">· {stage_name}</span></div>
      <div style="margin-top:10px;font-size:14px">
        🟢 {n_green} &nbsp; 🟡 {n_yellow} &nbsp; 🔴 {n_red} &nbsp; ⚪ {n_skip} (not applicable)
      </div>
      <div style="margin-top:12px;height:10px;background:#eaeef2;border-radius:6px;overflow:hidden">
        <div style="height:100%;width:{pct:.0f}%;background:{stage_color}"></div>
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:14px">{rows}</table>
    <div style="padding:12px 24px;background:#f6f8fa;color:#57606a;font-size:12px;border-top:1px solid #d0d7de">
      Read-only self-assessment · stages: Ad hoc → Repeatable → Managed → Automated → Optimized ·
      ⚪ checks were skipped (not accessible or not applicable) and don't count against the score.
    </div>
  </div>
</div>
"""
try:
    displayHTML(html)
except NameError:
    # Non-interactive (job) context — displayHTML isn't available; text output above stands in.
    print(f"\n===== MLOps Readiness: {pct:.0f}% · {stage_name} "
          f"(🟢{n_green} 🟡{n_yellow} 🔴{n_red} ⚪{n_skip}) =====")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8 · Next steps
# MAGIC
# MAGIC Prioritize the 🔴 items, then the 🟡. The typical path to "Automated":
# MAGIC 1. **Track everything** — `mlflow.autolog()`, signatures + input examples.
# MAGIC 2. **Register to Unity Catalog** with 3-level names; promote with **aliases**, not stages.
# MAGIC 3. **Serve from UC** models by alias; turn on **inference tables**.
# MAGIC 4. **Monitor** inference tables with Lakehouse Monitoring.
# MAGIC 5. **Automate** with Git + Databricks Asset Bundles across dev/staging/prod.
# MAGIC
# MAGIC Re-run this notebook after each engagement session to watch the score climb. 📈

# COMMAND ----------

# Machine-readable summary (handy for exporting / trend tracking across sessions).
summary = {
    "overall_pct": round(pct, 1),
    "stage": stage_name,
    "counts": {"green": n_green, "yellow": n_yellow, "red": n_red, "skip": n_skip},
    "checks": [
        {"area": c.area, "title": c.title, "status": c.status, "detail": c.detail}
        for c in RESULTS
    ],
}
import json
print(json.dumps(summary, indent=2))

# When run as a job/DAB task, return the summary so it can be captured downstream.
try:
    dbutils.notebook.exit(json.dumps(summary))
except Exception:
    pass
