# Phase (b): Metric Designer and validation

Goal: from a confirmed Semantic Brief and assessed sources, generate a UC metric view, let the user edit
it with live schema validation, and prove it correct in a sandbox before anything is published.

## Principles carried over from phase (a)

- The model never writes SQL or YAML text. It returns a structured model; the server checks every
  table and column against live `DESCRIBE` profiles and renders the YAML.
- Every DDL (including the sandbox `CREATE OR REPLACE VIEW ... WITH METRICS`) shows the exact SQL and
  runs only after approval, as the user, through the audited runner.
- Test queries are reads and run as the user.

## Steps

1. **Metric view schema (shared, client and server).** zod schema for YAML `version: 1.1`: `source`,
   `comment`, `filter`, recursive `joins` (`on` or `using`, never both), `dimensions` and `measures`
   with `comment`, `synonyms` (max 10), `display_name` (max 255), `format` (discriminated by `type`).
   Semantic checks: unique names, `MEASURE()` references resolve, join alias is not a prefix of a
   fact column, full dot-chain for nested join columns, columns exist in the profiles, joins are
   many-to-one when keys are declared. Parse with the `yaml` package. Unit tests with golden TPC-H YAML.
2. **Lakebase migration 003.** `metric_view_draft` (project, version, name, yaml, explanations jsonb,
   status draft|validated), `validation_run` (draft version, statement, results jsonb, outcome).
3. **Generation prompt `designer.generate`.** Input: brief plus live profiles of the sources. Output:
   fact source, join tree with keys, dimensions, measures with additivity class and a plain-language
   explanation, display names, synonyms, formats, and 3-5 test cases (dimensions + measures).
   Server validates names, renders YAML, stores draft v1. Refine works like the brief.
4. **Designer page.** YAML editor (monospace text area, live validation with line-numbered errors)
   beside a model view: join tree as an ERD (inline SVG, keys on edges, fan-out warnings) and the
   measure and dimension lists with explanations. Save creates a new version.
5. **Validate in sandbox.** Approve the shown `CREATE OR REPLACE VIEW <sandbox>.<name>__gsb_<draft>`
   statement. Then for each test case run the `MEASURE()` query and an expanded plain-SQL equivalent
   that the server derives from the YAML (joins + measure expressions + `GROUP BY`). The expanded SQL
   is also what the UI shows as "the SQL the engine would produce". Compare row sets with a numeric
   tolerance; optionally compare against a user-provided reference query (read allowlist) or expected
   values. Show pass/fail per test; a draft becomes `validated` only when all pass.
6. **TPC-H demo and phase summary.** Net revenue model on `samples.tpch` with a snowflake join
   (orders -> customer -> nation -> region) and lineitem as the fact.

## Defaults (change if needed)

- Sandbox for validation views: a bundle variable `sandbox_schema`, dev default
  `sandbox.genie_semantics_builder`. Sandbox views are dropped only through an approved statement.
- Generated YAML targets `version: 1.1`. Window measures need `version: 0.1`, which drops semantic
  metadata, so the generator does not emit them; the editor accepts them with a warning.
- Materialization is out of scope here (phase d).

## Risks

- Expanded-SQL equivalence is exact only for additive and simple ratio measures; composed or
  distinct-count measures compare per test row, not by rollup.
- `DESCRIBE` per source on every generation adds a few seconds; acceptable at TPC-H scale.
- `DROP VIEW` is not on the allowlist yet; adding it only for `__gsb_` sandbox names is part of step 5.
