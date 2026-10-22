# Best practices — fix-order, placement, anti-patterns

Guidance for turning a scan report into safe, high-leverage improvements. These
mirror Genie Workbench's optimizer priorities, condensed for a single space.

## Fix-order (highest leverage first)

Work findings in this order; earlier layers unlock the later ones:

1. **Data sources & metric views** — a space with no data sources (check 1) or
   too many (check 6) is structural. Resolve this before anything else.
2. **Metadata: table and column descriptions + synonyms** (checks 2, 3, 9,
   lever 1) — the single biggest driver of correct table/column routing.
3. **Joins** (check 5, lever 4) — add missing join specs so multi-table
   questions resolve. Every join `sql` needs the equijoin line plus the
   `--rt=...--` relationship annotation.
4. **Example SQL & benchmarks** (checks 7, 10, lever 6) — teach the patterns
   Genie should follow; add `usage_guidance` so examples are applied in the
   right context.
5. **General instructions** (check 4, lever 5) — last, because instructions are
   the most error-prone surface and should not carry logic that belongs in SQL
   expressions.

## Instruction placement (pick ONE vocabulary)

Keep text instructions to a single block. Use the near-term GSL section
vocabulary (five `##` headers, in order):

`## PURPOSE` -> `## DISAMBIGUATION` -> `## DATA QUALITY NOTES` ->
`## CONSTRAINTS` -> `## Instructions you must follow when providing summaries`.

- Put routing/definition logic into descriptions, synonyms, SQL expressions,
  and example SQL — not into prose instructions.
- Each `content` element should end with a newline.
- Do not exceed 2000 chars in the text block (a warning threshold); prefer
  expressions and examples over long prose.

## Anti-patterns to fix

- **SQL logic in prose instructions** (check 4 warning) — move it into a SQL
  expression, measure, filter, or an example SQL with `usage_guidance`.
- **Entity matching on RLS / masked tables** — Genie silently disables it there.
  Never enable it on a table the RLS audit marks `tainted`.
- **Over-enabling entity matching** — the value-dictionary cap is 120 columns
  per space; enabling it broadly wastes slots. Target high-cardinality
  categorical columns, never PII columns.
- **Descriptions that restate the column name** — descriptions should add
  business meaning, grain, and disambiguation, not echo the identifier.
- **Missing `usage_guidance` on example SQL** — without it, examples are applied
  in the wrong context (check 7 advisory).
- **Incomplete join specs** — a join missing `left`, `right`, or the `--rt=`
  annotation breaks the space; `optimize.py` drops incomplete joins rather than
  write a broken config.

## Augment, do not overwrite

When improving existing content, incorporate what is already there; only
replace a value when it is empty or wrong. Preserve user-authored synonyms,
descriptions, and instruction sections. This keeps optimization non-regressive.

## Composition with native curation

This skill is the deterministic gate; native Genie Code curation is the
LLM-reasoned fixer. A good loop:

1. Run `scan.py` -> get the score, tier, and ranked findings.
2. For nuanced fixes (semantics from a conversation, a specific failed message),
   let native curation draft the change.
3. For rubric-driven fixes, draft patches per `fix-contract.md`, preview the
   diff, and apply with approval.
4. Re-run `scan.py` to confirm the score improved before promoting the space.

## Proving improvement (optional, when benchmarks exist)

If the space has >= 10 benchmarks (check 10 passes), you can validate an edit by
asking Genie the benchmark questions before and after and comparing results with
an arbiter. Keep any held-out benchmark questions out of the space's example SQL
(no leakage). The full multi-iteration benchmark loop stays in Genie Workbench.
