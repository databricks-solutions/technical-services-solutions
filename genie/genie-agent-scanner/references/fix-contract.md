# Fix contract — how to draft a safe patch

During guided optimize, YOU (the agent) draft config fixes; `optimize.py`
validates, applies, and diffs them. This file is the contract you must follow so
a fix is valid, safe, and reversible. It mirrors Genie Workbench's Quick-Fix
patch contract, expressed as named operations.

## `fixes.json` schema

Write approved fixes to `fixes.json` as a JSON array (or `{"fixes": [...]}`) of
operation objects:

```jsonc
{
  "check_id": 2,                              // int 1..12, optional — which scan check this addresses
  "operation": "set_table_description",       // required — see the operation table
  "target": { "identifier": "cat.sch.tbl" },  // locator; keys depend on the operation
  "new_value": ["..."],                       // payload; shape depends on the operation
  "rationale": "why this fixes the finding"   // optional
}
```

### Operations

| operation | target keys | new_value | fixes check |
|-----------|-------------|-----------|-------------|
| `set_table_description` | `identifier` | `str` or `[str]` | 2 |
| `set_column_description` | `identifier`, `column_name` | `str` or `[str]` | 3 |
| `add_column_synonyms` | `identifier`, `column_name` | `[str]` (existing kept, deduped) | 3 |
| `enable_entity_matching` | `identifier`, `column_name` | `bool` optional (also sets format assistance) | 9 |
| `enable_format_assistance` | `identifier`, `column_name` | `bool` optional | 9 |
| `set_text_instruction` | `id` optional | `str` or `[str]` (lines forced to end `\n`; single block) | 4 |
| `add_example_sql` | — | `{question, sql, usage_guidance?, parameters?, id?}` | 7 |
| `add_join_spec` | — | `{left, right, sql:[cond, "--rt=...--"], comment?, instruction?, id?}` | 5 |
| `add_sql_snippet` | `kind`: `filter`\|`expression`\|`measure` | `{display_name, sql, synonyms?, instruction?, id?}` | 8 |
| `add_sql_function` | — | `{identifier}` or string | 8 |
| `add_benchmark_question` | — | `{question, sql, id?}` | 10 (note) |
| `add_sample_question` | — | `{question}` or string | — |
| `set_field` | `path` (dot/bracket) | any | raw escape hatch |

Note on `add_benchmark_question` (check 10): the operation is allowed (LOW-risk)
and seeds benchmark rows, but it does NOT by itself *satisfy* check 10. Check 10
reflects genuine benchmark curation — authored questions with verified answers,
run through the benchmark / optimization workflow — which is a user-driven
process, not a config patch. So a fix must NOT claim `check_id: 10`, and
`optimize.py` rejects one that does (see `references/scan-checks.md`). Use the
operation to seed benchmarks, never to "pass" the check.

Appended entries get a deterministic 32-char lowercase-hex id
(`sha256(canonical_json)[:32]`, matching Genie's id format) so the same input
always produces the same PATCH; override with `new_value.id`.

Rules:
- Output valid JSON only. Keep values concise (1-2 sentences for descriptions).
- Include `check_id` for traceability whenever you can.
- At most 50 fixes per pass; do the most important items first.

## Risk tiers (drives apply vs propose)

`optimize.py --apply` may apply LOW and MEDIUM operations once the user approves
the diff. There are deliberately **no HIGH-risk operations in v1** — structural
edits are not offered by `optimize.py` and must be done manually or via native
curation.

- **LOW (apply after approval):** `set_table_description`,
  `set_column_description`, `add_column_synonyms`, `enable_entity_matching`,
  `enable_format_assistance`, `add_example_sql`, `add_sample_question`,
  `add_benchmark_question`.
- **MEDIUM (apply after approval, review the diff carefully):**
  `set_text_instruction`, `add_join_spec`, `add_sql_snippet`,
  `add_sql_function`, and any `set_field`.
- **HIGH (NOT supported in v1 — propose to the user, do manually):** add or
  remove a table, update TVF SQL, add/remove a TVF, update metric-view YAML.

## Valid field paths (reference for `set_field` and for understanding writes)

`set_field` and the sanitizer operate on these exact paths. Names matter:
`example_question_sqls` (NOT `sql_examples`), `text_instructions` (NOT
`general_instructions`), `synonyms` inside `column_configs`.

```
data_sources:
- data_sources.tables[N].identifier                              string, catalog.schema.table
- data_sources.tables[N].description                             array of strings
- data_sources.tables[N].column_configs[N].column_name           string
- data_sources.tables[N].column_configs[N].description           array of strings
- data_sources.tables[N].column_configs[N].synonyms              array of strings
- data_sources.tables[N].column_configs[N].exclude               boolean
- data_sources.tables[N].column_configs[N].enable_entity_matching     boolean
- data_sources.tables[N].column_configs[N].enable_format_assistance   boolean
- data_sources.metric_views[N].identifier                        string (same structure as tables)

instructions:
- instructions.text_instructions[N].content                      array of strings (MAX 1 block per space). Preserve every existing ## Section header.
- instructions.example_question_sqls[N].question                 array of strings
- instructions.example_question_sqls[N].sql                      array of strings (one line per element)
- instructions.example_question_sqls[N].usage_guidance           array of strings
- instructions.sql_functions[N].identifier                       string (catalog.schema.function)
- instructions.join_specs[N].left                                object {identifier, alias} — REQUIRED
- instructions.join_specs[N].right                               object {identifier, alias} — REQUIRED
- instructions.join_specs[N].sql                                 array of EXACTLY 2 strings: (1) `alias`.`col` = `alias`.`col`; (2) --rt=FROM_RELATIONSHIP_TYPE_<TYPE>--
- instructions.sql_snippets.filters[N].{display_name, sql, synonyms, instruction}
- instructions.sql_snippets.expressions[N].{alias, display_name, sql}
- instructions.sql_snippets.measures[N].{alias, display_name, sql}

config & benchmarks:
- config.sample_questions[N].question                            array of strings
- benchmarks.questions[N].question                               array of strings
- benchmarks.questions[N].answer[N].format                       string ("SQL")
- benchmarks.questions[N].answer[N].content                      array of strings
```

## Preserve canonical instruction sections (GSL)

A single text-instruction block may use these canonical `##` headers, in order:
`## PURPOSE`, `## DISAMBIGUATION`, `## DATA QUALITY NOTES`, `## CONSTRAINTS`,
`## Instructions you must follow when providing summaries` (the last is
verbatim-required). When editing the text instruction:
- Preserve ALL existing `## Section` headers. Edit bullets within a section, or
  insert a new canonical section at the correct ordered position.
- If a fix would require deleting a canonical header, do not make it — surface
  the conflict to the user instead.

## Sanitization guardrails (applied automatically before PATCH)

`optimize.py` performs these, and you should assume them:
- Re-fetch the fresh config immediately before applying (avoids "modified since
  export" conflicts).
- Ensure every id is 32-char lowercase hex; generate deterministic ids for
  appended entries in id-bearing arrays (`sample_questions`,
  `text_instructions`, `example_question_sqls`, `join_specs`, `filters`,
  `expressions`, `measures`, `questions`, `sql_functions`).
- A join `sql` MUST be exactly the equijoin line plus the
  `--rt=FROM_RELATIONSHIP_TYPE_<TYPE>--` annotation, or the space fails to parse;
  incomplete joins (missing `left`/`right`) are rejected.
- Dedupe and sort where the schema requires it; force text-instruction lines to
  end with `\n`.
- **Preserve unknown / unrecognized fields verbatim** on round-trip — the tool
  never drops config it did not touch. (Note: it does not strip to the API's
  top-level allowlist; validate against a real space during live testing.)

## Budgets and limits

- `serialized_space` version = 2. Genie's top-level keys: `version`, `config`,
  `data_sources`, `instructions`, `benchmarks`.
- Instruction slot budget = 100 (each example SQL + each SQL function + the one
  text block + each described table + each described metric view; joins and
  snippets excluded).
- SQL snippet budget = 200 (filters + expressions + measures).
- Max string length 25,000; max array size 10,000.
- IDs are 32-char lowercase hex, unique within their collection.
- `(table_identifier, column_name)` must be unique.

## Write API

- Read: `GET /api/2.0/genie/spaces/{id}?include_serialized_space=true`.
- Write: `PATCH /api/2.0/genie/spaces/{id}` with body
  `{"serialized_space": "<json string of the config>"}`.
- The space title/description is a top-level PATCH field, NOT inside
  `serialized_space`.
