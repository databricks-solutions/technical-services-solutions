# genie-space-scan-optimize

A condensed, portable Agent Skill that ports Databricks Genie Workbench's
scan -> scored report -> guided optimize against a single Genie space/agent,
without installing the Workbench app. It is a derivative work of the public
Genie Workbench accelerator and is distributed under the same Databricks License
(see `LICENSE.md` / `NOTICE.md`). Authored to the open Agent Skills standard so
it runs in Genie Code (primary), Claude Code, and Cursor.

> **Not a replacement for Genie Workbench — a stopgap.** This is a small, local
> alternative you can reach for *while* you get the full Genie Workbench app
> installed. It deliberately covers only part of what Workbench does; the goal
> is to unblock the day's work in the meantime, not to be a complete
> replacement for the Workbench experience.

## Why this while you install the Workbench app
- **Light.** No app, no backend, no Lakebase, no service to deploy or host --
  just a small folder you drop into `.assistant/skills/` (or back with a Git
  folder). The security-review surface is a handful of readable Markdown +
  Python files, with no network egress beyond the workspace's own Genie / Unity
  Catalog APIs. Use it today to keep moving while the full Workbench app is
  being installed.
- **Deterministic and fast.** The 12-check IQ score comes from a pure, no-LLM
  scorer -- same input, same score, no model calls and no SQL warehouse in the
  scan path -- so results are reproducible and match Workbench's rubric.
- **Meets authors where they already are.** Runs inside Genie Code (and Claude
  Code / Cursor) as one portable artifact, complementing native Genie Code
  curation as the deterministic quality gate rather than duplicating it.

## Install
This is a standard Agent Skill: a folder with a `SKILL.md` at its root.
Installing it means dropping that folder into your assistant's skills directory
-- there is nothing to build, deploy, or host. It is **not** a Unity Catalog
object: agent skills are plain workspace / local files (only MCP *servers* are
UC-governed), so `.assistant/skills/` (Genie Code) and `~/.claude/skills/`
(Claude Code) folders are the whole install surface.

First get the folder. It ships as a solution inside the Databricks Technical
Services Solutions repo, under `genie/genie-agent-scanner/`:
```
# clone the solutions repo (or sparse-checkout just this folder)
git clone https://github.com/databricks-solutions/technical-services-solutions.git
cd technical-services-solutions/genie/genie-agent-scanner
```
The skill's own `name` is `genie-space-scan-optimize` (that is the invocation
token). When you drop it into an assistant's skills directory below, name the
installed folder to match the skill -- `genie-space-scan-optimize/` -- so
`@genie-space-scan-optimize` resolves cleanly.

**Genie Code (primary).** Copy the `genie-space-scan-optimize/` folder into a
skills directory in your Databricks workspace:
- Personal: `/Workspace/Users/<your-email>/.assistant/skills/genie-space-scan-optimize/`
- Workspace-wide (admin only): `/Workspace/.assistant/skills/genie-space-scan-optimize/`

Or, in the Genie Code pane, click the **Settings** gear -> **Open skills
folder** and drop it there. Back the folder with a Databricks Git folder to
version, share, and roll back across the team. After adding or editing the
skill, start a **new** chat -- edits do not affect an active chat (hard-refresh
if it still looks stale).

**Claude Code.** Copy the folder into either:
- Personal (all projects): `~/.claude/skills/genie-space-scan-optimize/`
- This project only: `.claude/skills/genie-space-scan-optimize/`

It is picked up live in the current session -- no restart. Invoke it in plain
language ("scan this Genie space") or explicitly with
`/genie-space-scan-optimize`.

**Cursor.** Drop the same folder into Cursor's skills directory; Cursor loads
the identical `SKILL.md`. (The Databricks CLI below can place it for you with
`--agents cursor`.)

**Python (local runs only).** Live and offline scans run the scorer in
`scripts/`, so install its dependencies once:
```
pip install -r scripts/requirements.txt
```
The Databricks SDK is imported lazily -- fully offline scans
(`--serialized-space-file`) need no SDK, and runs **inside Genie Code** need no
local Python at all, since the agent gathers the config with its native tools.

> **`databricks aitools install`.** Databricks ships a CLI that auto-detects
> your installed coding agents and distributes *published* skills to each one
> (e.g. `databricks aitools install --agents claude-code`). This skill is WIP
> and not published to that catalog yet, so install it manually with the steps
> above for now.

Status: WIP. Unsupported community port; published for early feedback.

## License & attribution
This project is a derivative work of the public Databricks Genie Workbench
accelerator (`databricks-solutions/databricks-genie-workbench`) and is
distributed under the **Databricks License** — see the repository-root
[`LICENSE.md`](../../LICENSE.md). The deterministic scoring rubric and lever
mapping in `scripts/genie_space_iq/` are ported/adapted from that repository's
`genie-space-optimizer` package; see [`NOTICE.md`](./NOTICE.md) for attribution.
It is an unsupported community port, **not** an official Databricks product,
certification, or supported feature.
