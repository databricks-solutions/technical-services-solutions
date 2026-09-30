# Routing rule — which Databricks surface does a workbook become?

Every workbook routes to exactly one **kind** of end-state asset. The rule is deterministic and
derivable straight from the workbook XML, so the mapping is defensible
("here's *why* this became a Genie space, not a dashboard"). It is **purpose-only** — it answers
*what should this become on Databricks?*, never *how hard is it?* (no complexity / effort /
compatibility scoring). `scripts/route.py` implements it (`parse_twbx.py` calls it after parsing
the raw files); you override any single call by editing `target:` in the mapping.

## The rule (evaluated top to bottom, first match wins)

| # | Condition | Becomes | Why |
|---|-----------|---------|-----|
| 1 | `params ≥ 3` **and** `n_calcs > 40` | **Databricks App** | Params-as-inputs + heavy calc logic = a what-if / estimator *tool*, not a report. Forcing it into a dashboard produces the loudest complaints. |
| 2 | purpose is error / exception / status / monitoring (name or `purpose`/`drivers` match) | **SQL Alert** | These exist to fire when something breaks, not to be browsed. A dashboard nobody watches misses the point. |
| 3 | `text_pct ≥ 95%` **and** `datasources ≤ 2` | **Genie space** | ≥95% text marks = people open it to read/filter/export a table. That is the Genie interaction model; rebuilding it as a dashboard reproduces the worst of the estate. |
| 4 | everything else | **Lakeview dashboard** | Genuine visual analytics. |

`text_pct` is the fraction of a workbook's marks that are text/crosstab. From raw `.twbx` it is
computed from the `<mark class=…>` histogram (explicit `Text` marks ÷ all marks) — a heuristic:
Tableau's default `Automatic` marks are counted as visual, so a crosstab built without an explicit
Text mark can read low. For the hand-filled template, supply it directly (or `crosstab`/`yes` →
treated as 1.0). Sanity-check the Genie-routed rows while curating.

## Two standing assumptions (state them to the customer — they print on the report)

1. **All reports assumed in use.** Nothing is retired for low usage (worst case; trim later with
   Tableau Server usage stats). Duplicates still fold in — that's structural, not usage-based.
2. **All data assumed movable to Databricks.** External / opaque sources (Athena, Redshift,
   published datasources, shadow Excel/CSV) are migration *targets*, not blockers. This makes
   routing **purpose-only** — every workbook gets a real home instead of being parked as "blocked."

## What the rule does NOT decide (you curate these)

- **Consolidation** — how many workbooks collapse into one asset. The rule picks a *kind* per
  workbook; `parse_twbx.py` seeds a provisional group per shared **fact table**, but merging sibling
  facts into one named business asset (and splitting oversized ones) is yours to confirm.
- **Retire vs. keep** — duplicate detection (copy-paste forks, dated snapshots, `_test`/`_V2`).
  Set `target: RETIRE` + `survivor:` by hand; these are judgment calls the customer must confirm.
- **The semantic layer** — Metric Views are *seeded* from the real calc fields (metrics, time
  dimension, detected drift), but which ones truly exist and what they standardize is the
  highest-value curation; see the Metric View guidance in `SKILL.md`.

## Tuning

Thresholds live at the top of `scripts/route.py` (`APP_PARAM_MIN`, `APP_CALC_MIN`,
`GENIE_TEXT_PCT`, `GENIE_MAX_DS`) and the `MONITOR_RE` keyword set. Adjust per engagement if a
customer's estate skews the signals.
