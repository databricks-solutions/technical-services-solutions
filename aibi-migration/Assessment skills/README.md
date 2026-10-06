# Assessment Skills

Workspace skills that support the AI/BI migration process. Each skill lives in
its own subfolder and can be run independently from Databricks Assistant / Genie.

## Skills

| Skill | Folder | Purpose |
|---|---|---|
| **pbi-migration-assessment** | [`pbi-migration-assessment/`](pbi-migration-assessment) | Bulk profiling & migration-readiness assessment for Power BI reports, as a wrapper around `/importBI`. |

## Installing a skill

Each skill needs its own subfolder containing a `SKILL.md`. You can install it
in one of two places.

### Personal (user) skill

- Save the skill's folder to `/Workspace/Users/[user@databricks.com]/.assistant/skills/`.
- Only you can see and use it.

### Workspace (shared) skill

Use this when the whole team should use the same version of the skill, rather
than each person keeping a copy in their personal folder.

- A **workspace administrator** saves the skill's folder to
  `/Workspace/.assistant/skills/`, for example
  `/Workspace/.assistant/skills/pbi-migration-assessment/SKILL.md`.
- Everyone in the workspace can use it. Admins can also grant other users
  access to the skills folder so they can add or update skills.
- Keep only one copy. If the same skill is also in a personal folder, delete
  the personal copy so nobody runs an outdated version.
- When prompting, refer to the skill by name ("the pbi-migration-assessment
  skill") instead of "my … skill", or use the `@` mention to invoke it
  explicitly.

See [Genie Code skills](https://docs.databricks.com/aws/en/assistant/skills)
for details.

---

## pbi-migration-assessment

A custom skill that wraps `/importBI` to produce a consolidated Power BI
migration assessment report.

It runs a **read-only profiling pass** over one or more Power BI report files
(`.pbit`) — either attached directly or bulk-loaded from a Unity Catalog Volume —
without performing any conversion. For each report it profiles the data sources,
data model, DAX measures, visualizations, filters, and interactivity, then
consolidates the findings into a single Migration Assessment Report. The report
flags prerequisites and blockers and classifies every feature into an
automate-vs-manual split anchored to what `/importBI` handles today (✅ Auto /
⚠️ Auto + workaround / 🔧 Manual), plus an automation-uplift estimate from
applying UC semantics patterns during migration.

> [!CAUTION]
> **Disclaimer — estimates, not guarantees.** The assessment and the
> conversion are performed by an AI agent (`/importBI` and this skill) that
> relies on large language models. Both are under active development, so
> results may vary between runs and may not be fully accurate or complete.
> Complexity ratings, ✅/⚠️/🔧 classifications, automation percentages, and
> uplift estimates are indicative and intended to support planning only.
> Have a qualified team member review the report against the source
> `.pbit` files, and validate converted dashboards and metric views against
> the original Power BI reports before relying on them for project scoping,
> effort estimates, commitments, or production use.

> [!NOTE]
> If you observe on some runs that the skill is abandoned and the process falls
> back to plain `/importBI` assessment, prompt additionally:
> "use the pbi-migration-assessment skill to wrap up the migration report".

> [!IMPORTANT]
> The Automation Uplift section of the assessment and the pattern-based
> conversion both read
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> live. This needs **access to GitHub from the Databricks workspace** (outbound
> network to github.com). Without it, the Uplift section shows "Pattern repo
> unavailable — uplift not computed" and the conversion cannot apply the recipes.

### User journey

#### 1. Run the assessment
- Install the `pbi-migration-assessment` folder (see [Installing a skill](#installing-a-skill)).
- Open a new dashboard page.
- In Genie Code: "assess the Power BI report with my pbi-migration-assessment skill" (attach the file, or point to the volume).
  For a workspace skill, say "with the pbi-migration-assessment skill".
- Review the result in the chat.

**Get the main report and the manual adjustments list in one run.** To receive
the detailed 🔧 Manual Adjustment Report together with the assessment, ask for
it in the first prompt:

```
Assess the Power BI report(s) <attached file | in /Volumes/<catalog>/<schema>/<volume>/>
with the pbi-migration-assessment skill. After the main Migration Assessment Report,
also produce the detailed 🔧 Manual Adjustment Report: list every 🔧 Manual measure
with its table and a short reason, grouped as in the Feature Classification table,
and check that the counts match the summary.
```

#### 2. Get the detailed 🔧 Manual Adjustment Report
- When the main report is finished, the skill asks whether you want a detailed
  🔧 Manual Adjustment Report. Answer "yes".
- If the skill didn't ask, or you want the report later, prompt in the same
  conversation: "create the 🔧 Manual Adjustment Report for the
  manual-adjustment measures from the assessment".
- The report groups the 🔧 measures the same way as the Feature Classification
  table and gives each measure a short reason, e.g. `Matrix Display | TREATAS
  on literals + ISINSCOPE + FORMAT text`. It ends with a consistency line
  checked against the 🔧 counts in the main report.
- Use it to plan and assign the manual work.

#### 3. (Optional) Save results
- First switch the Genie Code context to your workspace user folder
  (`/Workspace/Users/[user@databricks.com]/`) and stay in the same
  conversation. Do not start a new chat, or the results are lost.
- Then prompt: "save results in MD and HTML format in my user folder". This
  saves the main assessment and, if you created it, the Manual Adjustment Report.

#### 4. Convert with uc-semantics-patterns (when the assessment shows uplift)
Use this step when the **Automation Uplift with Reference Patterns** section
lists 🔧 features that can be reclassified and shows a positive uplift (+pp).
It needs GitHub access from the workspace (see the note above). If the
assessment said "Pattern repo unavailable", fix the access and rerun the
assessment, or skip this step.

- Start the conversion with `/importBI` and add the repo as an extra reference
  for converting calculations. You don't need to list specific measures.
- Example prompt:

  ```
  /importBI Convert the report [attach the report, or provide a volume path], as additional
  reference for the calculations conversion use https://github.com/databricks-solutions/uc-semantics-patterns
  ```

- Tips:
  - After conversion, check the ⚠️ items against the report's Validation Checks.
  - Items that remain 🔧 (see the Manual Adjustment Report) still need manual work.
