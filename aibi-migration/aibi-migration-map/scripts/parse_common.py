#!/usr/bin/env python3
"""
parse_common.py — shared parsing helpers for the raw-file front-ends.

Both `parse_twbx.py` (Tableau) and `parse_pbit.py` (Power BI) extract the same shapes —
upstream tables, calculated fields / measures, a fact-table group key — and seed Metric Views
the same way (candidate metrics + cross-source drift). That common logic lives here so the two
tools stay consistent and the routing/render pipeline downstream is identical.
"""
import re
import collections

# ---- table classification (used for fact-table clustering) ---------------
# A "fact" carries measures/events; a "dim" is a lookup; the calendar dim is conformed.
FACT_RE = re.compile(r"(_fct$|_fact$|_data$|_txn$|_rev\b|fact_|^fact|_facts?$)", re.I)
FCT_STRICT_RE = re.compile(r"(_fct$|_fact$|fact_|^fact)", re.I)  # a true fact table outranks a _data sidecar
# dimension naming across Tableau + Power BI conventions: _dim, dim_, dim.., Dim*, D_*, *dimension*
DIM_RE = re.compile(r"(_dim$|^dim[._ ]?|dim_|^dimensions?[._ ]?|_dimension$|^d_)", re.I)
# calendar/date dim: clndr, calendar, dimdate, date_dim, d_date, *date* as a whole table token
CALENDAR_RE = re.compile(r"(clndr|calendar|dim_?date|date_?dim|d_date|\bcal\b|^date$|_date$|\bdate\b|date$)", re.I)
NOISE_RE = re.compile(r"^extract\.|^\[?extract\]?$|^sqlproxy$|^federated|^parameters$|^custom sql", re.I)

TABLE_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w]*\.[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)", re.I)

# aggregations that mark a calc/measure as a real metric — Tableau + DAX vocabularies
AGG_RE = re.compile(
    r"\b(SUM|SUMX|AVG|AVERAGE|AVERAGEX|COUNT|COUNTX|COUNTD|DISTINCTCOUNT|COUNTROWS|MIN|MINX|MAX|MAXX"
    r"|MEDIAN|WINDOW_\w+|TOTAL|RUNNING_\w+|CALCULATE|DIVIDE)\s*\(|/", re.I)
COPY_RE = re.compile(r"\s*\((?:copy|copy \d+)\)\s*$|_copy$|_old(_[\w]+)?$|_v\d+$|_\d{4,}$", re.I)
# captions that are UI/logic plumbing, not metrics — kept out of the metric seed
NON_METRIC_RE = re.compile(
    r"filter|flag|\blabel\b|sort|colou?r|tooltip|param|dashboard|\bview\b|reset|blank|hidden"
    r"|\bnote\b|definition|glossary|header|title|selector|\bcheck\b|drilldown|isblank|\bhelper\b"
    r"|^\W*i\W*$", re.I)


def base_caption(cap):
    """Normalize a field/measure name so 'Avails', 'Avails (copy)', 'Avails_V2' collapse to one key."""
    c = re.sub(r"\s+", " ", (cap or "")).strip()
    prev = None
    while c != prev:
        prev = c
        c = COPY_RE.sub("", c).strip()
    return c


def norm_formula(f):
    return re.sub(r"\s+", " ", (f or "")).strip().lower()


def classify(tok):
    t = tok.lower()
    if NOISE_RE.search(t):
        return "noise"
    if CALENDAR_RE.search(t):
        return "calendar"
    if DIM_RE.search(t):
        return "dim"
    if FACT_RE.search(t):
        return "fact"
    return "other"


def is_metric(base, formula, require_agg=True):
    """A calc/measure worth seeding as a metric: not a placeholder, not UI plumbing, and (for
    Tableau calc fields) actually aggregating. Power BI measures are metrics by definition, so
    callers pass require_agg=False there and only the plumbing filter applies."""
    if not base or base.startswith("Calculation_"):
        return False
    if NON_METRIC_RE.search(base):
        return False
    f = (formula or "").strip()
    if (f.startswith('"') and f.endswith('"')) or (f.startswith("'") and f.endswith("'")):
        return False  # a string-literal label, not a metric
    return bool(AGG_RE.search(formula)) if require_agg else True


# schema/layer/type tokens dropped when turning a physical table name into a readable subject
_STOP = {"dm", "dl", "fct", "fact", "dim", "dims", "data", "ss", "mr", "fn", "vw", "dpl",
         "tbl", "tb", "prod", "gold", "silver", "bronze", "raw", "stg", "stage", "core"}


def humanize_entity(label, phys=None):
    """Turn a fact-table token (e.g. 'retail_dm.dm_inventory_fct', 'MR_Margin_DPL') into a readable
    subject ('Inventory', 'Margin') for a suggested Metric View name."""
    seg = (phys or label).split(".")[-1]
    parts = [p for p in re.split(r"[_\s\-]+", seg) if p]
    kept = [p for p in parts if p.lower() not in _STOP] or parts
    return " ".join(w[:1].upper() + w[1:] for w in kept) or seg


def suggest_semantics(label, metrics, phys=None):
    """Best-effort Metric View title / purpose / grain from what the files told us, so the batch
    (non-interactive) output isn't full of bare TODOs. These are DRAFTS — the wording invites the
    curator to confirm; only `owner` stays a hard TODO (unknowable from the files)."""
    subject = humanize_entity(label, phys)
    real = [m for m in metrics if m and m != "TODO"]
    egs = ", ".join(real[:3])
    title = f"{subject} Metrics"
    if real:
        purpose = (f"Standardizes the {len(real)} metrics below on {label}"
                   + (f" (e.g. {egs})" if egs else "") + " — confirm each definition while curating.")
    else:
        purpose = f"The metrics standardized on {label} — add them while curating."
    grain = f"One row per {subject} record — confirm the true grain."
    return title, purpose, grain


def seed_from_calcs(items, require_agg=True):
    """items: iterable of (name, formula, source_key) across one group.
       Returns (metrics, drift):
         metrics — deduped metric names (first-seen order), the Metric View's candidate metrics
         drift   — [[name, message]] where the same metric has ≥2 distinct formulas; cross-source
                   drift (defined differently in different files/workbooks) sorts first.
    """
    metric_caps, seen = [], set()
    formulas_by_cap = collections.defaultdict(lambda: collections.defaultdict(set))  # base -> formula -> {src}
    for name, formula, src in items:
        b = base_caption(name)
        if not b:
            continue
        formulas_by_cap[b][norm_formula(formula)].add(src)
        if is_metric(b, formula, require_agg) and b.lower() not in seen:
            seen.add(b.lower())
            metric_caps.append(b)

    drift = []
    for b, fmap in formulas_by_cap.items():
        real = {f for f in fmap if f}
        if len(real) < 2 or b.startswith("Calculation_") or NON_METRIC_RE.search(b):
            continue
        nsrc = len({s for ss in fmap.values() for s in ss})
        if nsrc >= 2:
            msg = f"{len(real)} different formulas across {nsrc} files — pick one definition"
        else:
            msg = f"{len(real)} formula variants (copy-forks) in one file — reconcile to one"
        drift.append((0 if nsrc >= 2 else 1, b.lower(), [b, msg]))
    drift.sort()
    return metric_caps, [d[2] for d in drift]
