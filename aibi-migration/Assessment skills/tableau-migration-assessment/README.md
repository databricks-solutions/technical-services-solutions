# Tableau Migration Assessment

A read-only profiling skill that assesses Tableau files for migration to
Databricks AI/BI dashboards. It profiles each file, classifies every feature as
automatable / automatable-with-workaround / manual (anchored to the `/importBI`
migration agent), and estimates the automation uplift from applying
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns).

It **does not convert anything** — no datasets, no widgets, no dashboards are created.

## User journey

1. Install the `tableau-migration-assessment` folder (see
   [Adding the skill in Genie Code](#adding-the-skill-in-genie-code)).
2. Open a new dashboard page.
3. In Genie Code: *"assess the Tableau workbook with my tableau-migration-assessment
   skill"* (attach the file, or point to the volume).
4. Review the result in the chat — a single report, Migration Summary first, then
   the per-file detail sections.
5. The skill then stores an **HTML version** of the report to a Databricks workspace
   path. If you didn't give one, it asks where to save it before writing.

## Supported file types

| Type | What it is | Profiled as |
|---|---|---|
| `.twb` | Raw workbook XML | Full workbook |
| `.twbx` | Zipped workbook (XML + extracts + resources) | Full workbook |
| `.tds` | Raw data-source definition (connection + calc fields) | Model-only |
| `.tdsx` | Zipped data source (`.tds` + extract) | Model-only |

`.tds` / `.tdsx` have no worksheets, dashboards, filters, or actions, so their
visual/interaction sections collapse into a single model-only callout.

## Adding the skill in Genie Code

This skill follows the open [Agent Skills](https://docs.databricks.com/aws/en/genie-code/skills)
standard, so adding it to **Genie Code** is just a matter of dropping its folder
into a `.assistant/skills/` directory — no packaging or marketplace step. Genie
Code loads it automatically the next time you start a chat.

First pick where it lives:

- **User skill (just you):** `/Users/<your-username>/.assistant/skills/` — good for
  personal use or prototyping before promoting it to the workspace.
- **Workspace skill (whole workspace):** `Workspace/.assistant/skills/` — makes it
  available to everyone. Requires access to the workspace skills folder (ask a
  workspace admin if you don't have it).

Then:

1. In the **Genie Code** pane, click **Settings → Open skills folder** to jump to
   the right `.assistant/skills/` directory (user or workspace).
2. Create a folder named `tableau-migration-assessment/` inside it.
3. Add this skill's **`SKILL.md`** to that folder. `SKILL.md` is required — its
   `name` / `description` frontmatter is what Genie Code uses to auto-load the
   skill. (`README.md` is optional; it's just this overview.)
   ```
   /Users/<your-username>/.assistant/skills/
   └── tableau-migration-assessment/
       └── SKILL.md
   ```
4. Start a **new chat**. Genie Code picks up the skill automatically. Edits to a
   skill only take effect in new chats — if it still looks stale, hard-refresh the
   browser tab to clear cached skill metadata.

> **Tip:** back your `.assistant/skills/` folder with a **Databricks Git folder** to
> version the skill and share it with your team.
>
> **Other agents:** because `SKILL.md` is Agent-Skills-standard, the same skill also
> installs into Claude Code, Cursor, or GitHub Copilot via the Databricks
> agent-skills plugin path — see
> [Agent skills for AI coding assistants](https://docs.databricks.com/aws/en/agent-skills).

## How to invoke

Once the skill is in your `.assistant/skills/`, there are two ways to invoke it:

**1. Automatically (description-triggered)** — Genie Code loads it on its own when
you ask to **assess, profile, audit, or evaluate** Tableau files for migration.
Point it at either a Unity Catalog Volume or attached files. No mention needed.

Assess a UC Volume (bulk):
```
Assess the Tableau files in /Volumes/catalog/schema/volume/ for AI/BI migration.
```

Assess attached files:
```
Profile these workbooks for migration complexity. <attach .twb/.twbx/.tds/.tdsx files>
```

Other phrasings that trigger it:
- "Profile these Tableau workbooks for migration."
- "What's the migration complexity / blockers / readiness of these files?"
- "Audit this .tdsx before we convert it to a Databricks dashboard."

**2. Explicitly (@ mention)** — force Genie Code to use it by @-mentioning the
skill in your prompt:
```
@tableau-migration-assessment profile these workbooks for AI/BI migration.
```

## What it does

1. **Enumerate** — lists all `.twb` / `.twbx` / `.tds` / `.tdsx` files at the path
   (or uses attached files) and reports the count before proceeding.
2. **Prerequisites check** — flags connection strings/parameters to resolve,
   non-Databricks sources (and their in-source transforms — custom SQL, unions,
   cross-DB joins, filters — to rebuild as source views), `.hyper` extracts, the
   source-table inventory, source dependencies (never drop a source another object
   uses), and relationship/join quality (disconnected sources, fact-to-fact,
   mismatched keys, many-to-many, cardinality overrides).
3. **Profile** — hands each file to the `/importBI` specialist in **profile-only**
   mode. With **2+ files, profiling runs in parallel batches of up to 4 at a time**;
   a single file is profiled directly.
4. **Report** — produces ONE report that opens with the **Migration Summary Report**
   and is followed by one **Individual Workbook Report** section per file. Runs a
   pre-print hygiene check (counts reconcile and stay consistent across the report).
5. **Export HTML** — stores an HTML version of the report to a Databricks workspace
   path, asking for the path first if one wasn't provided.

## Output

ONE report, in this order:

- **Migration Summary Report** (opens the report): portfolio totals, complexity
  distribution, per-file summary, cross-cutting findings, and a recommended
  migration sequence.
- **Individual Workbook Report** (one section per file, after the summary): metrics,
  prerequisites, executive overview + complexity drivers, feature inventory,
  Automation Classification (✅ Auto / ⚠️ Auto + workaround / 🔧 Manual), Automation
  Uplift with reference patterns, and a readiness summary that **names the 🔧 Manual
  items** (top 10, with a one-line reason) so you can plan the manual rebuild.

The report is returned in chat (summary first, then the per-file sections) and also
saved as an HTML file to a workspace path you supply.

## Skill definition (`SKILL.md`)

`SKILL.md` is the authoritative specification for this skill — `README.md` is only
an overview. Anyone installing, running, or adapting the skill should read
`SKILL.md`, which defines the required details the assessment must follow:

- **Trigger & scope** — the `description` frontmatter that auto-loads the skill,
  and the supported file types.
- **Workflow** — enumerate → prerequisites check → profile (read-only, via
  `/importBI` in profile-only mode, parallel batches of up to 4) → produce one report
  (hygiene-checked) → export the HTML to a workspace path.
- **Mandatory report structure** — the exact headings and tables for **Template A
  (Migration Summary Report, opens the report)** and **Template B (Individual
  Workbook Report, one section per file, after the summary)**. These formats are
  required, not examples.
- **Deduplication & Empty Report Handling** rules.
- **Automation Classification Legend** (✅ Auto / ⚠️ Auto + workaround / 🔧 Manual)
  and the **Complexity Rating Criteria** (Low / Medium / High).
- **Guardrails** — read-only, `/importBI`-anchored classification, no unevidenced
  claims, Tableau-only terminology, group ✅/⚠️ but name 🔧 items, the pre-print
  hygiene check, source-dependency handling, and the mandatory Automation
  Classification + Automation Uplift sections.
- **Reference Patterns** — the uc-semantics-patterns catalog, plus LOD-decomposition,
  table-calculation, and cross-datasource / blend-ratio (fact ÷ dimension vs
  fact ÷ fact) recipes that drive the Automation Uplift section.

If the behavior described in this README ever diverges from `SKILL.md`, `SKILL.md`
wins.

## Notes

- **Read-only.** The skill never converts, creates datasets, or creates widgets —
  this constraint applies to parallel subagents too.
- **Tableau only.** Power BI files use a separate framework
  (`pbi-migration-assessment`).
- Classification reflects what `/importBI` handles **today**; the Automation Uplift
  section shows the additional automation achievable with uc-semantics-patterns
  recipes on top of that baseline.
