# MLOps Readiness Scorecard

A **read-only** Databricks notebook a customer runs in *their own* workspace to
self-assess how they're doing ML today against Databricks MLOps best practices —
**before** an MLOps engagement, so the session targets real gaps instead of guesses.

Output: a 🟢/🟡/🔴 scorecard across four areas (Tracking · Model management ·
Serving & monitoring · Engineering discipline), an overall maturity stage
(Ad hoc → Repeatable → Managed → Automated → Optimized), and per-check
*why it matters* + *how to fix*.

- [Quick start](#run-it-3-ways)
- [How scoring works](#how-scoring-works)
- [How to read the output](#how-to-read-the-output) ← worked example
- [Every check explained](#every-check-explained) ← full rubric
- [Requirements & limitations](#requirements)

---

## Run it (3 ways)

**A. Import the notebook (easiest for a live session)**
1. In the customer workspace: **Workspace → Import → File**, choose
   `mlops_readiness_scorecard.py` (imports as a notebook — the `# COMMAND ----------`
   markers become cells).
2. Attach to any cluster or serverless.
3. **Run All**. Read the scorecard at the bottom.

**B. CLI import**
```bash
databricks workspace import \
  /Workspace/Users/<you>/mlops_readiness_scorecard \
  --file mlops_readiness_scorecard.py --language PYTHON --format SOURCE
```

**C. From a Git folder / Repo** — commit this file and clone the repo into the
workspace, then Run All.

### Options (notebook widgets)
| Widget | Default | Purpose |
|---|---|---|
| `catalog_scope` | *(all)* | Limit UC checks to one catalog; also enables the Feature-table check |
| `max_models_sampled` | 50 | How many registered models to inspect |
| `signature_sample` | 8 | How many models to deep-load for signature checks (slower) |
| `check_serving` | true | Toggle serving-endpoint inspection |

---

## How scoring works

Each check returns one of four states:

| State | Meaning | Score |
|:---:|---|:---:|
| 🟢 GREEN | Best practice in place | 1.0 |
| 🟡 YELLOW | Partially there / inconsistent | 0.5 |
| 🔴 RED | Practice missing | 0.0 |
| ⚪ SKIP | Couldn't check (no access / not applicable / feature off) | *excluded* |

**Overall % = (sum of scored points) ÷ (number of 🟢/🟡/🔴 checks) × 100.**
⚪ SKIP checks never count against you — a locked-down or non-UC workspace simply
scores on fewer checks rather than being penalised for what couldn't be inspected.

The percentage maps to a **maturity stage**:

| Overall | Stage | Reading |
|---|---|---|
| 0–24% | **Ad hoc** | ML happens, but untracked and ungoverned |
| 25–49% | **Repeatable** | Some tracking/registration, inconsistent |
| 50–74% | **Managed** | Core practices in place; gaps in serving/monitoring/CICD |
| 75–89% | **Automated** | UC + aliases + serving + bundles working together |
| 90–100% | **Optimized** | Monitoring closes the loop; fully automated promotion |

Sampling is **capped** (`LIST_CAP`, widget limits) so the notebook stays fast even
on huge workspaces — counts like "34 runs sampled" reflect the sample, not the total.

---

## How to read the output

At the bottom of the notebook you get a scorecard banner + a table. Here's a **real
run** (against a large shared workspace) annotated line-by-line.

```
===== MLOps Readiness: 67% · Managed  (🟢5 🟡2 🔴2 ⚪5) =====
```
> **Headline:** 67% → *Managed*. Read it as "the fundamentals are there, but the
> production loop (UC promotion + monitoring) isn't closed yet." The counts tell you
> where to spend the session: 2 reds are the must-fix items; 5 skips are just
> not-applicable / not-accessible here.

| Check | Result | How to read it |
|---|---|---|
| 🟢 Experiments logged | `200 experiments; 34 runs sampled` | Training **is** being tracked in MLflow. Good foundation. |
| 🟡 Params / metrics / autolog | `only 1/34 sampled runs log both params & metrics` | Runs exist but most are sparse (e.g. eval/trace runs) → **turn on `mlflow.autolog()`** so every run is comparable. |
| 🔴 Models in Unity Catalog | `0 UC models, but 11 in the legacy registry` | The **headline gap**: models live in the deprecated Workspace Registry, not UC. This is the #1 thing to fix — no UC governance/lineage/cross-workspace access. |
| ⚪ Aliases (Champion/Challenger) | `no UC models to inspect` | Skipped *because* there are no UC models yet — it'll light up once they migrate. Not a penalty. |
| 🔴 No deprecated stages | `1 version still using Staging/Production` | They're still promoting via **stages** (deprecated). Move to UC **aliases**. |
| ⚪ Models documented / signatures | `no UC models to inspect` | Same as aliases — pending UC migration. |
| 🟢 Model Serving endpoints | `91 endpoints deployed` | Real-time serving is in use. |
| 🟡 Inference tables | `only 3/15 endpoints log inference tables` | Most endpoints don't log payloads → **you can't monitor them**. Enable inference tables. |
| ⚪ Lakehouse Monitoring | `can't enumerate monitors from this SDK version` | Tooling limitation, not a finding — see [limitations](#known-limitations). |
| 🟢 Git-backed code (Repos) | `20 Git repos` | Code is version-controlled. |
| 🟢 CI/CD (Asset Bundles) | `282 jobs deployed via Asset Bundles` | Strong — deployments are code-defined and promotable. |
| 🟢 Environment separation | `catalogs span tiers: nonprod, prod` | Isolated environments exist for promotion. |
| ⚪ Feature Engineering in UC | `set the catalog_scope widget to enable` | Off by default — set `catalog_scope` to turn it on. |

**How to run the session from this:** attack 🔴 first (migrate to UC + aliases),
then 🟡 (autolog everywhere; enable inference tables), then close the loop with
monitoring. Re-run afterwards to watch the score climb.

> 🟡/🔴 rows in the notebook also print a **Why** and **Fix** line underneath — the
> concrete next action for that gap. 🟢 and ⚪ rows stay compact.

---

## Every check explained

### Tracking & experiments
| Check | 🟢 | 🟡 | 🔴 | Why it matters |
|---|---|---|---|---|
| **Experiments logged** | experiments with runs exist | — | experiments but no runs / none at all | Untracked training = no reproducibility, comparison, or lineage |
| **Params / metrics / autolog** | ≥70% of sampled runs log both params & metrics | some do | none do | Params+metrics per run are the minimum to compare & govern models. Fix: `mlflow.autolog()` |

### Model management (Unity Catalog)
| Check | 🟢 | 🟡 | 🔴 | Why it matters |
|---|---|---|---|---|
| **Models in Unity Catalog** | models in UC, none in legacy | UC **and** legacy both used | 0 UC / only legacy, or none anywhere | UC gives governance, lineage, cross-workspace access. Legacy Workspace Registry is deprecated. `system.ai.*` foundation models are excluded from the count. |
| **Aliases (Champion/Challenger)** | all sampled UC models use aliases | some do | none do | Aliases are how UC promotes models (stages are deprecated) — serving references `models:/…@Champion` |
| **No deprecated stages** | no legacy stage usage | legacy models exist, no stages | versions still on Staging/Production | MLflow stages are deprecated in favor of aliases |
| **Models documented** | ≥70% have descriptions | some do | none do | Undocumented models can't be governed or handed over |
| **Model signatures** | all sampled models have a signature | some do | none do | Signatures enable schema validation and are required for many serving paths. Fix: `signature=infer_signature(...)` + `input_example` |

### Serving & monitoring
| Check | 🟢 | 🟡 | 🔴 | Why it matters |
|---|---|---|---|---|
| **Model Serving endpoints** | ≥1 endpoint | no endpoints (not every use case needs serving) | — | Production ML usually needs real-time or batch serving |
| **Inference tables** | all sampled endpoints log payloads | some do | none do | Payload logging is the foundation for monitoring & drift detection |
| **Lakehouse Monitoring** | monitors configured | none detected | — | Monitoring closes the loop — catch drift/quality regressions before users do |

### Engineering discipline
| Check | 🟢 | 🟡 | 🔴 | Why it matters |
|---|---|---|---|---|
| **Git-backed code (Repos)** | ≥1 Git repo | — | no repos | Notebooks-only work has no version control, review, or CI/CD hook |
| **CI/CD (Asset Bundles)** | jobs deployed via Bundles | jobs exist, none via Bundles | no jobs at all | Bundles (DABs) give code-defined, environment-promotable, CI/CD-friendly deployments |
| **Environment separation** | catalogs span ≥2 tiers (dev/staging/prod/nonprod) | one tier detected | — | Promoting models dev→staging→prod needs isolated environments |
| **Feature Engineering in UC** | PK (feature-ready) tables in scope | none in scope | — | Feature tables need a primary key to back Feature Engineering / online lookups. *Requires `catalog_scope`.* |

---

## Requirements
- **Databricks Runtime ML** — `mlflow` + `databricks-sdk` are pre-installed; the
  dependency cell is a no-op.
- **Serverless / plain runtime** — the first cell auto-installs `mlflow-skinny` +
  `databricks-sdk` and restarts Python (adds ~30s).
- UC checks require the workspace to be on Unity Catalog; anything not accessible is
  marked ⚪ and excluded from the score.

## Safety
100% read-only — it only **lists and reads** metadata via the MLflow client and
`databricks-sdk`. It never creates, edits, or deletes anything. Every probe is wrapped
so one broken/forbidden API can't sink the run; that check just becomes ⚪ SKIP.

## Status
Smoke-tested end-to-end on a live workspace (serverless): all four areas run,
`system.ai.*` foundation models are correctly excluded, and legacy-registry /
deprecated-stages / Asset-Bundle / inference-table detection all fire.

### Known limitations
- **Lakehouse Monitoring** shows ⚪ on SDK versions without a monitor-list API.
- **Environment separation** and **Feature Engineering** are heuristics (catalog
  naming; primary-key tables) — treat as directional signals, not hard facts.
- Counts are sampled/capped to stay fast on large workspaces, so they reflect the
  sample rather than workspace totals.

## Re-running
Re-run after each MLOps session to watch the score climb. The last cell prints a
machine-readable JSON summary (also returned via `dbutils.notebook.exit`) you can
persist to a table for trend tracking.
