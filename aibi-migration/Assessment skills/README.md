# Assessment Skills

Genie Code skills that support the AI/BI migration process. Each skill lives in
its own subfolder and can be run independently from Genie Code.

All skills in this folder share the same approach:

- **Read-only.** They profile source BI files and produce a Migration Assessment
  Report — they never convert anything or create datasets, widgets, or dashboards.
- **Anchored to `/importBI`.** Each skill wraps the
  [`/importBI`](https://docs.databricks.com/aws/en/dashboards/manage/import-bi)
  migration agent in profile-only mode. Every feature is classified by what
  `/importBI` reports it can handle today: ✅ Auto / ⚠️ Auto + workaround / 🔧 Manual.
- **Automation uplift.** An extra section estimates how much more can be automated
  by applying [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
  recipes during migration.

## Skills

| Skill | Source files | Purpose |
|---|---|---|
| [**pbi-migration-assessment**](pbi-migration-assessment) | `.pbit` / `.tmdl` | Bulk profiling & migration-readiness assessment for Power BI reports and semantic models. |
| [**tableau-migration-assessment**](tableau-migration-assessment) | `.twb` / `.twbx` / `.tds` / `.tdsx` | Bulk profiling & migration-readiness assessment for Tableau workbooks and data sources. |

Each skill folder has its own README with supported file types, example prompts,
workflow, and output details.

## Prerequisites

- A Databricks workspace with **Genie Code** and the **`/importBI`** agent available
  (partner-powered AI features enabled for the account and workspace — see
  [Import BI files using Genie Code](https://docs.databricks.com/aws/en/dashboards/manage/import-bi)).
- Source files either attached in the chat or stored in a **Unity Catalog Volume**.
  Files over 100 MB, and any bulk assessment, must be in a Volume — direct chat
  uploads are limited to 100 MB and not accepted for bulk import.
- **Outbound access to github.com** from the workspace. The Automation Uplift
  section and the pattern-based conversion read
  [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
  live at each run. Without it, the Uplift section shows "Pattern repo
  unavailable — uplift not computed" and the conversion cannot apply the recipes.

## Disclaimer

> [!CAUTION]
> **Estimates, not guarantees.** The assessment and the conversion are performed
> by AI agents (`/importBI` and these skills) that rely on large language models.
> Both are under active development, so results may vary between runs and may not
> be fully accurate or complete. Complexity ratings, ✅/⚠️/🔧 classifications,
> automation percentages, and uplift estimates are indicative and intended to
> support planning only. Have a qualified team member review the report against
> the source files, and validate converted dashboards and metric views against the
> original reports before relying on them for project scoping, effort estimates,
> commitments, or production use.

## Installing a skill

These skills follow the open [Agent Skills](https://docs.databricks.com/aws/en/assistant/skills)
standard, so installing one is just a matter of dropping its folder into a
`.assistant/skills/` directory — no packaging or marketplace step.

### 1. Pick where it lives

- **User skill (just you):** `/Workspace/Users/[user@databricks.com]/.assistant/skills/`
  — good for personal use or prototyping before promoting it to the workspace.
- **Workspace skill (whole team):** `/Workspace/.assistant/skills/` — everyone in
  the workspace uses the same version. Requires access to the workspace skills
  folder (a workspace admin can save it, or grant others access to add or update
  skills).

> [!TIP]
> Keep only one copy. If the same skill is installed both as a workspace skill
> and in a personal folder, delete the personal copy so nobody runs an outdated
> version.

### 2. Add the skill folder

1. In the **Genie Code** pane, click **Settings → Open skills folder** to jump to
   the right `.assistant/skills/` directory (user or workspace).
2. Create a folder named after the skill, e.g. `pbi-migration-assessment/`.
3. Add the skill's **`SKILL.md`** to that folder. `SKILL.md` is required — its
   `name` / `description` frontmatter is what Genie Code uses to load the skill.
   (`README.md` is optional; it is only an overview.)
   ```
   /Workspace/.assistant/skills/
   ├── pbi-migration-assessment/
   │   └── SKILL.md
   └── tableau-migration-assessment/
       └── SKILL.md
   ```
4. Start a **new chat**. Edits to a skill only take effect in new chats — if it
   still looks stale, hard-refresh the browser tab to clear cached skill metadata.

> [!TIP]
> Back your `.assistant/skills/` folder with a **Databricks Git folder** to version
> the skills and share them with your team.
>
> **Other agents:** because `SKILL.md` follows the Agent Skills standard, the same
> skills also install into Claude Code, Cursor, or GitHub Copilot — see
> [Agent skills for AI coding assistants](https://docs.databricks.com/aws/en/agent-skills).

## How to invoke

Call the skill explicitly with an `@` mention in the prompt:

```
@tableau-migration-assessment profile these workbooks for AI/BI migration.
```

Genie Code can also pick the skill up from a prompt like "assess these Power BI
reports for migration", but this isn't guaranteed — without the explicit call the
run may fall back to the default `/importBI` assessment.

## User journey

The journey is the same for every skill; see each skill's README for
ready-to-copy prompts.

1. **Install** the skill folder (see [Installing a skill](#installing-a-skill)).
2. **Open a new dashboard page** and start a chat in Genie Code.
3. **Run the assessment** — call the skill with `@`, e.g.
   *"`@<skill-name>` assess the report(s) `<attached file | in /Volumes/...>`"*.
   To get the detailed 🔧 Manual Adjustment Report in the same run, ask for it in
   the first prompt.
4. **Review the result** in the chat.
5. **Get the 🔧 Manual Adjustment Report** — if you didn't ask for it up front, the
   skill offers it after the main report; answer "yes". It names every 🔧 item
   with a short reason, so you can plan and assign the manual work.
6. **Save the results (optional)** — first switch the Genie Code context to your
   workspace user folder (`/Workspace/Users/[user@databricks.com]/`) *in the same
   conversation*, then prompt: *"save results in MD and HTML format in my user
   folder"*.
7. **Convert (when ready)** — when the Automation Uplift section shows a positive
   uplift, start the conversion with `/importBI` and add the patterns repo as an
   extra reference for the calculations. You don't need to list specific items.
   ```
   /importBI Convert the report [attach the file, or provide a volume path], as additional
   reference for the calculations conversion use https://github.com/databricks-solutions/uc-semantics-patterns
   ```
   After conversion, check the ⚠️ items against the report's Validation Checks;
   items that remain 🔧 still need manual work.

## Troubleshooting

| Symptom | What to do |
|---|---|
| The skill is abandoned and the run falls back to a plain `/importBI` assessment | Prompt additionally: *"`@<skill-name>` wrap up the migration report"*. |
| The skill isn't picked up, or old behavior persists after an edit | Start a new chat; if still stale, hard-refresh the browser tab. |
| Uplift section says "Pattern repo unavailable" | Enable outbound access to github.com from the workspace and rerun the assessment, or skip the pattern-based conversion. |
| Results are gone after saving | Results only exist in the current conversation — switch context and save *before* starting a new chat. |

## Skill definition

Each skill's `SKILL.md` is the authoritative specification — the READMEs are only
overviews. If a README ever diverges from `SKILL.md`, `SKILL.md` wins.
