# pbi-migration-assessment — change log

Every entry records what changed and **why** (the failure that drove it, when
known), so the reasoning behind each rule survives future edits. When you change
the skill, add an entry here and update the version in `README.md`.

Entries are newest first.

---

## 2.0.0 — 2026-10-27

- **Bulk runs report per file and per portfolio.** A Migration Summary Report
  opens the report, followed by one Individual Report per file, each with its own
  Automation Summary and Uplift. *Why:* bulk runs only showed a pooled rate, so one
  large or hard file skewed the rate for every file.
- **Outliers flagged and shown separately**, with the portfolio rate also shown
  excluding outliers and as a per-file median. *Why:* same skew problem.
- **Compact reports for 6+ files**, with a follow-up offer of the full report for
  chosen files. *Why:* long runs did not fit in one reply.
- **One pass, no pausing.** Files are profiled in one turn with only progress lines,
  and each `/importBI` answer is reduced to a short digest. *Why:* runs stopped
  after file 1 and asked the user to reply "continue" for each file.
- **Uplift mandatory everywhere.** The patterns repo is read once per run, every
  header shows whether it was read, and the summary has its own Uplift section.
  When nothing matches, the section is a single "no uplift" line. *Why:* the Uplift
  went missing in a bulk run.
- **Uplift (pp) defined per row.** *Why:* the per-file median row showed +0 next to
  different baseline and with-patterns values.
- **`.tmdl` support** (semantic models → metric views) and a link to the
  `/importBI` documentation.
- **🔗 `EXTERNALMEASURE` measures** are flagged and excluded from every rate, with a
  prompt to assess the source semantic model separately. *Why:* their logic lives in
  a remote model and was distorting the rate.
- **New counting rules:**
  - business vs display measures;
  - Auto % vs Auto with review %;
  - root 🔧 measures and their dependents;
  - a fixed list of feature groups;
  - auto date/time tables excluded;
  - shared models counted once;
  - no unused exclusion for model-only files or shared models;
  - layer rates.

  *Why:* measure counts alone overstated effort and hid model and visual work.
- **Complexity rating** is now a points score with a visible breakdown.
- **🔧 Manual Adjustment Report** uses the same format whether requested up front
  or later. It is organised by root 🔧 measures and runs its own consistency check.
  *Why:* the one-pass prompt had to spell out the format.
- **Skill text consolidated** into one Rules list, with each rule stated once.

---

## 1.1.0 — 2026-10-06

- Fixes to the assessment skill.

---

## 1.0.0 — 2026-10-01

- Initial release.
