# Phase (c2): Guided experience and semantic readiness

Goal: make the app feel like a Databricks product and guide the customer from intent to a validated metric view.
Every screen uses Du Bois components and tokens, works in light and dark mode, has the four data states and meets
WCAG AA. Test data: the `sandbox_source` catalog (copies of the samples schemas, managed tables).

## Principles carried over

- The model never writes SQL or YAML text. All DDL shows the exact SQL and runs only after approval, as the user.
- Lakebase stores metadata only. Warehouse access is OBO.

## Steps

1. **Home page.** Project cards with progress (brief, sources, design, validated), owner, last activity, and a
   search. "New project" asks only for a name and a business goal. No catalog or schema pickers.
2. **Projects and sub-projects.** A project is a business domain (for example Sales). A sub-project is one metric
   view with its own brief, sources, design, validations and pattern runs. The project page lists its sub-projects
   with their status. Migration moves each existing project into one sub-project.
3. **Guided intake (chat).** Claude interviews the user with the brief questions, one at a time, and suggests
   answers from what it already knows. The user can mention `@catalog.schema.table` (autocomplete from the
   catalogs the user can read). A side panel shows the brief draft as it fills in, with open questions. The user
   confirms the brief at the end. The existing brief schema and confirm flow stay.
4. **Source readiness and semantic score.**
   - Sources: add tables from the chat mentions, from the picker, or as a group. "Bring related tables" suggests
     tables that the selected ones reference (declared foreign keys, then key-name matches such as `o_custkey` to
     `customer.c_custkey`, in the same schema). The user adds several tables at once.
   - Ontology view: the business entities of the brief (Customer, Order, Product) mapped to tables, and the
     relationships between them as a graph. Unmapped entities and unlinked tables are shown as gaps.
   - Semantic readiness score per table and per sub-project, 0-100, from weighted areas: documentation (table and
     column comments), keys and relationships (PK, FK, RELY), types (dates, numeric amounts), naming clarity,
     and coverage of the brief (each measure and dimension has a source column). Each area shows its score and why.
   - Improvement plan: the open findings ranked by score gain, each with the approved-DDL fix that exists today
     (comments, PK, FK) and the score it would add.
5. **Permissions panel.** For the current user, a live check of each privilege the app needs: CAN USE on the
   warehouse, USE CATALOG and USE SCHEMA plus SELECT on each source, USE SCHEMA and CREATE TABLE on the sandbox
   schema, and MODIFY or ownership for approved comment and key fixes. Pass or fail per item, with the GRANT a
   catalog owner would run. Shown on the sources page and before any DDL.
6. **Modeling patterns.** Rename Playground to "Modeling patterns". Each pattern opens on its example (scenario,
   question, result). "Try in playground" runs the one test of the pattern. A compatibility badge per pattern for
   the current sub-project: the server matches the pattern roles to the source columns by type and name, no AI
   ("Fits: date and amount found" or "Missing: snapshot date"). "Apply to my data" is offered when it fits.
7. **Metric Designer.** Tabs Model, YAML, Tests and History. Measure and field cards that lead with the
   explanation, a larger join diagram, the next step always visible (fix errors, validate, publish later).
8. **Visual review and demo.** Check every page in light and dark mode. Demo on `sandbox_source.tpch`: chat intake,
   related tables, score before and after approved fixes, a compatible pattern, design, validation.

## Defaults (change if needed)

- The intake chat uses the existing Claude serving endpoint. Genie cannot run an interview.
- Compatibility is rule-based. The AI is used only when the user applies a pattern.
- Score weights: documentation 30, keys and relationships 30, types 15, naming 10, brief coverage 15.

## Risks

- Effective privilege checks: `SHOW GRANTS` lists direct grants only, so inherited and group grants can be missed.
  The panel shows a fail as "not found" and keeps the real query result as the final proof.
- The chat adds model calls per turn. Each turn is traced (metadata only) and limited in length.
- The sub-project migration changes keys of every metadata table; it is tested on local Postgres first.
