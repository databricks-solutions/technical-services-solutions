# Assessment Skills

Workspace skills that support the AI/BI migration process. Each skill lives in
its own subfolder and can be run independently from Databricks Assistant / Genie.

## Skills

| Skill | Folder | Purpose |
|---|---|---|
| **pbi-migration-assessment** | [`pbi-migration-assessment/`](pbi-migration-assessment) | Bulk profiling & migration-readiness assessment for Power BI reports, as a wrapper around `/importBI`. |

## Installing a skill

- Save the skill's folder to `/Workspace/Users/[user@databricks.com]/.assistant/skills/`.

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

> [!NOTE]
> If you observe on some runs that the skill is abandoned and the process falls
> back to plain `/importBI` assessment, prompt additionally:
> "use the pbi-migration-assessment skill to wrap up the migration report".

**User journey**
- Install the `pbi-migration-assessment` folder (see [Installing a skill](#installing-a-skill)).
- Open a new dashboard page.
- In Genie Code: "assess the Power BI report with my pbi-migration-assessment skill" (attach the file, or point to the volume).
- Review the result in the chat.
- (optional) Switch to the user folder and "save results in MD and HTML format in my user folder".
