# genie-agent-scan-optimize — scripts

The deterministic Python layer of the `genie-agent-scan-optimize` skill. Two
CLI entrypoints plus the `genie_space_iq` package. **No LLM. No hidden network
calls.** `scan.py` is a read-only quality gate; `optimize.py` applies
caller-drafted fixes and defaults to a dry-run diff.

```
scripts/
  genie_space_iq/
    api.py       # Genie Spaces REST GET/PATCH (round-trip preserves unknown fields)
    model.py     # typed, read-only view over serialized_space
    checks.py    # the 12 deterministic checks + SQL-in-prose detector
    scoring.py   # IQ score (0-12) + 3-tier maturity
    levers.py    # SCAN_CHECK_TO_LEVERS bridge (check -> optimization lever)
    report.py    # machine JSON + human markdown report
    fixes.py     # deterministic fix validation / application / unified diff
  scan.py        # CLI: READ-ONLY scan
  optimize.py    # CLI: apply caller-drafted fixes (dry-run by default)
  tests/         # pytest suite + JSON fixtures (no live calls)
  requirements.txt
```

## Requirements

Python 3.10+. Install dev + runtime deps:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
```

`databricks-sdk` is imported **lazily** — offline scans and the whole test suite
run without it. It is only needed for live `--space-id` fetches and `--apply`.

## Scan

Deterministic IQ scan → score out of 12, maturity tier (`Not Ready` /
`Ready to Optimize` / `Trusted`), per-check pass/warn/fail, and ranked next steps.

```bash
# Live (Databricks SDK default auth; optional --profile):
python scripts/scan.py --space-id <SPACE_ID> --json-out scan.json --md-out scan.md

# Live by title: resolve a space NAME to its id via a READ-ONLY listing, then scan.
# The match is trimmed + case-insensitive and must resolve to exactly one space;
# on zero/multiple matches it lists the candidate titles and exits non-zero.
python scripts/scan.py --space-name "Retail Analytics"

# Offline (no API): a raw serialized_space, an API export, or an envelope
# {"serialized_space": {...}, "optimization_run": {...}}:
python scripts/scan.py --serialized-space-file space.json
```

`--space-id`, `--space-name`, and `--serialized-space-file` are mutually
exclusive (exactly one is required). `--space-name` pages the Genie spaces
listing (`GET /api/2.0/genie/spaces`, read-only, no SQL warehouse) following
`next_page_token`, then scans the resolved id exactly as `--space-id` would.

Checks 11–12 are *optimization outcomes*. They need an `optimization_run`
(supplied via an envelope sibling key or `--optimization-run-file`). Without one
they fail, so a config-perfect space tops out at **Ready to Optimize** — you only
reach **Trusted** after a real optimization run scores ≥85% accuracy.

### The 12 checks

| # | Check | Passes when | Lever |
|---|-------|-------------|-------|
| 1 | Data sources exist | ≥1 table or metric view | — |
| 2 | Table descriptions | ≥80% of tables described (MV-only auto-passes) | 1 |
| 3 | Column descriptions | ≥50% of columns described | 1 |
| 4 | Text instructions | ≥1 block, >50 chars | 5 |
| 5 | Join specifications | ≥1 join when >1 data source | 4 |
| 6 | Data source count 1–12 | 1 ≤ sources ≤ 12 | — |
| 7 | 8+ example SQLs | ≥8 example question/SQL pairs | 6 |
| 8 | SQL snippets | ≥1 filter/expression/measure/function | 6 |
| 9 | Entity/format matching | ≥1 column with entity/format matching | 1 |
| 10 | 10+ benchmark questions | ≥10 benchmark questions | — |
| 11 | Optimization workflow completed | an `optimization_run` exists | — |
| 12 | Optimization accuracy ≥ 85% | `optimization_run.accuracy` ≥ 0.85 | — |

A `warning` severity still counts as *passed* (e.g. 80–99% table coverage).

## Optimize

`optimize.py` applies fixes the host agent drafts (see schema below). Default is a
**dry-run** printing a unified diff of `serialized_space`; `--apply` performs the
round-trip PATCH, which **preserves every unknown/unrecognized field**.

```bash
# Dry-run against the live space (fetch, diff, do NOT write):
python scripts/optimize.py --space-id <ID> --fixes-file fixes.json

# Dry-run fully offline (no API):
python scripts/optimize.py --serialized-space-file space.json --fixes-file fixes.json --out patched.json

# Apply (round-trip PATCH):
python scripts/optimize.py --space-id <ID> --fixes-file fixes.json --apply
```

## `fixes.json` schema

A JSON **array** (or `{"fixes": [ ... ]}`) of fix objects:

```jsonc
{
  "check_id": 2,                 // int 1..12, optional — which scan check this addresses
  "operation": "set_table_description",  // required — see the operations table
  "target": { "identifier": "main.retail.orders" },  // locator; keys depend on operation
  "new_value": ["Orders fact table with revenue and dates."],  // payload; shape depends on operation
  "rationale": "Check 2 failed: table had no description."     // optional, free text
}
```

| operation | target keys | new_value | addresses |
|-----------|-------------|-----------|-----------|
| `set_table_description` | `identifier` | `str` or `[str]` | 2 |
| `set_column_description` | `identifier`, `column_name` | `str` or `[str]` | 3 |
| `add_column_synonyms` | `identifier`, `column_name` | `[str]` (existing kept, deduped) | 3 |
| `enable_entity_matching` | `identifier`, `column_name` | `bool` (optional, default `true`; also sets format assistance) | 9 |
| `enable_format_assistance` | `identifier`, `column_name` | `bool` (optional, default `true`) | 9 |
| `set_text_instruction` | `id` (optional) | `str` or `[str]` (each line forced to end `\n`; single block) | 4 |
| `add_example_sql` | — | `{question, sql, usage_guidance?, parameters?, id?}` | 7 |
| `add_join_spec` | — | `{left, right, sql:[cond, "--rt=...--"], comment?, instruction?, id?}` | 5 |
| `add_sql_snippet` | `kind`: `filter`\|`expression`\|`measure` | `{display_name, sql, synonyms?, instruction?, id?}` | 8 |
| `add_sql_function` | — | `{identifier}` or a string | 8 |
| `add_benchmark_question` | — | `{question, sql, id?}` (answer wrapped as `format:"SQL"`) | 10 |
| `add_sample_question` | — | `{question}` or a string | — |
| `set_field` | `path` (dot/bracket, e.g. `data_sources.tables[0].description`) | any | advanced/raw |

### Determinism & id generation

`apply_fixes` is a pure function of `(serialized_space, fixes)`: same input →
byte-identical output. Newly appended entries that need an id get a **content
hash** (`sha256(canonical_json)[:32]` → 32 lowercase hex chars, matching Genie's
id format) rather than a random UUID, so runs are reproducible and testable.
Supply `"id"` inside `new_value` to override.

Example `fixes.json`:

```json
[
  {
    "check_id": 2,
    "operation": "set_table_description",
    "target": { "identifier": "main.retail.orders" },
    "new_value": ["Order line facts including revenue and dates."]
  },
  {
    "check_id": 9,
    "operation": "enable_entity_matching",
    "target": { "identifier": "main.retail.products", "column_name": "category" }
  },
  {
    "check_id": 5,
    "operation": "add_join_spec",
    "new_value": {
      "left": { "identifier": "main.retail.orders", "alias": "o" },
      "right": { "identifier": "main.retail.customers", "alias": "c" },
      "sql": ["`o`.`customer_id` = `c`.`customer_id`", "--rt=FROM_RELATIONSHIP_TYPE_MANY_TO_ONE--"]
    }
  }
]
```

## Auth notes

Live modes use the Databricks SDK's default auth (`WorkspaceClient`) — env vars,
`~/.databrickscfg`, or a named profile via `--profile`. Read =
`GET /api/2.0/genie/spaces/{id}?include_serialized_space=true`; list (for
`--space-name` resolution) = `GET /api/2.0/genie/spaces` (paged, read-only);
write = `PATCH /api/2.0/genie/spaces/{id}` with `{"serialized_space": "<json>"}`.
The patch serializes the full space dict verbatim, so fields this tool does not
model are never dropped.

## Tests & lint

```bash
python -m pytest -q      # 124 tests, no network, no secrets
ruff check scripts/      # clean
```
