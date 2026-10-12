# Tableau Migration Assessment

A read-only profiling skill that assesses Tableau files for migration to
Databricks AI/BI dashboards. It profiles each file, classifies every feature as
automatable / automatable-with-workaround / manual (anchored to the `/importBI`
migration agent), and estimates the automation uplift from applying
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns).

It **does not convert anything** — no datasets, no widgets, no dashboards are created.

> [!CAUTION]
> The assessment — and the `/importBI` conversion it anchors to — is performed by
> an **LLM-based agent under active development**. Every count, classification, and
> automation estimate is **indicative** and must be **reviewed and validated** by a
> human before you plan or execute a migration. Treat the report as a starting
> point, not a guarantee.

> [!IMPORTANT]
> The Automation Uplift section (and the eventual conversion) reads the
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> repository **live at each run**, so the workspace running the skill needs
> outbound access to **github.com**. Without it, the uplift falls back to
> "Pattern repo unavailable — uplift not computed; baseline applies."

> [!NOTE]
> If you observe on some runs that the skill is abandoned and the process falls
> back to a plain `/importBI` assessment, prompt additionally:
> "use the tableau-migration-assessment skill to wrap up the migration report".

## User journey

1. Install the `tableau-migration-assessment` folder (see
   [Adding the skill in Genie Code](#adding-the-skill-in-genie-code)).
2. Open a new dashboard page.
3. **Run the assessment.** In Genie Code: *"assess the Tableau workbook with my
   tableau-migration-assessment skill"* (attach the file, or point to the volume).
   To get the detailed manual list in the same pass, add it to the prompt, e.g.
   *"assess the Tableau files in `/Volumes/catalog/schema/volume/` with my
   tableau-migration-assessment skill and include the 🔧 Manual Adjustment Report"*.
4. **Review the result** in the chat — a single report, Migration Summary first,
   then the per-file detail sections.
5. **Get the 🔧 Manual Adjustment Report** — if you did not ask for it up front, the
   skill offers it after the main report; accept to get every 🔧 item named with a
   reason.
6. **Save the results (optional)** — first switch context to your workspace user
   folder *in the same conversation*, then *"save results in MD and HTML format in
   my user folder"*.
7. **Convert (when ready)** — hand the file to `/importBI`, pointing it at the
   patterns repo for the calculation conversions:
   ```
   /importBI Convert the workbook [attach the file, or provide a volume path], as additional reference for the calculations conversion use https://github.com/databricks-solutions/uc-semantics-patterns
   ```

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

This skill follows the open [Agent Skills](https://docs.databricks.com/aws/en/assistant/skills)
standard, so adding it to **Genie Code** is just a matter of dropping its folder
into a `.assistant/skills/` directory — no packaging or marketplace step. Genie
Code loads it automatically the next time you start a chat.

First pick where it lives:

- **User skill (just you):** `/Workspace/Users/[user@databricks.com]/.assistant/skills/`
  — good for personal use or prototyping before promoting it to the workspace.
- **Workspace skill (whole workspace):** `/Workspace/.assistant/skills/` — makes it
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
   /Workspace/Users/[user@databricks.com]/.assistant/skills/
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

**2. Explicitly (@ mention)** — force Genie Code to use it by @-mentioning the
skill in your prompt (the most reliable way to keep the skill engaged):
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
   mode, asking it to state how it would handle each category (transformations,
   relationships by pattern, row-level calcs/groups/bins/sets, cross-datasource
   ratios, unconvertible calcs with names, unused calcs). With **2+ files, profiling
   runs in parallel batches of up to 4 at a time where the environment supports
   concurrent handoffs**, otherwise sequentially; a single file is profiled directly.
4. **Consolidate & report** — produces ONE report that opens with the **Migration
   Summary Report** and is followed by one **Individual Workbook Report** section
   per file. Buckets and handling text come only from the `/importBI` profile
   (anything it did not state is marked `Not stated by /importBI — verify` and 🔧).
5. **Consistency check (mandatory, silent)** — before printing, reconciles bucket
   counts to totals (minus unused calcs), confirms counts match everywhere, keeps
   row-level calcs out of the calc %, and checks portfolio totals equal the per-file
   sums.
6. **Offer the 🔧 Manual Adjustment Report** — after the main report (or inline if
   requested up front), lists every 🔧 item by name with a reason.

## Output

ONE report, in this order:

- **Migration Summary Report** (opens the report): portfolio totals, complexity
  distribution, per-file summary, cross-cutting findings, and a recommended
  migration sequence.
- **Individual Workbook Report** (one section per file, after the summary): metrics,
  prerequisites (including a **Data Source Transformations** table), executive
  overview + complexity drivers, a feature inventory with a grouped **Relationships**
  table and a separate **Row-level Calculations, Groups, Bins & Sets** block,
  Automation Classification (✅ Auto / ⚠️ Auto + workaround / 🔧 Manual), Automation
  Uplift with reference patterns, and a readiness summary.

Individual 🔧 item names are **not** inlined in the main report — they appear only
in the optional **🔧 Manual Adjustment Report**, which names every 🔧 calculated
field / LOD / table calc (no top-N cap) with the blocking reason so you can plan the
manual rebuild.

The report is returned in chat (summary first, then the per-file sections). You can
optionally ask to save the results in MD and HTML format in your user folder.

## Skill definition (`SKILL.md`)

`SKILL.md` is the authoritative specification for this skill — `README.md` is only
an overview. Anyone installing, running, or adapting the skill should read
`SKILL.md`, which defines the required details the assessment must follow:

- **Trigger & scope** — the `description` frontmatter that auto-loads the skill,
  and the supported file types.
- **Workflow** — enumerate → prerequisites check → profile (read-only, via
  `/importBI` in profile-only mode, parallel batches of up to 4 where supported,
  else sequential) → consolidate → **mandatory consistency check** → **offer the
  🔧 Manual Adjustment Report**.
- **Mandatory report structure** — the exact headings and tables for **Template A
  (Migration Summary Report, opens the report)** and **Template B (Individual
  Workbook Report, one section per file, after the summary)**, plus the **Manual
  Adjustment Report Structure**. These formats are required, not examples.
- **Deduplication & Empty Report Handling** rules.
- **Automation Classification Legend** (✅ Auto / ⚠️ Auto + workaround / 🔧 Manual,
  with the fact ÷ dimension vs fact ÷ fact split) and the **Complexity Rating
  Criteria** (Low / Medium / High).
- **Guardrails** — read-only, the **source-of-truth rule** (`/importBI` output is
  the only basis for buckets and handling text), `/importBI`-anchored classification,
  no unevidenced claims, Tableau-only terminology, group-don't-name in the main
  report, the mandatory consistency check, source-dependency handling, and the
  mandatory Automation Classification + Automation Uplift sections.
- **Reference Patterns** — read the uc-semantics-patterns repo **live at each run**
  (no hardcoded catalog), match 🔧 items to its current content, and cite the
  folder/recipe in the Uplift section.

If the behavior described in this README ever diverges from `SKILL.md`, `SKILL.md`
wins.

## Notes

- **Read-only.** The skill never converts, creates datasets, or creates widgets —
  this constraint applies to parallel subagents too.
- **`/importBI` is the source of truth.** Every ✅/⚠️/🔧 bucket and handling cell
  comes from the `/importBI` profile; anything it did not state is marked
  `Not stated by /importBI — verify` and classified 🔧 Manual.
- **Tableau only.** Power BI files use a separate framework
  (`pbi-migration-assessment`).
- Classification reflects what `/importBI` reports **today**; the Automation Uplift
  section shows the additional automation achievable with uc-semantics-patterns
  recipes (read live) on top of that baseline.
