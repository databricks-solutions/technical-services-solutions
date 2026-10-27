# tableau-migration-assessment — change log

Every entry records what changed and **why** (the failure that drove it, when
known), so the reasoning behind each rule survives future edits. When you change
the skill, add an entry here and update the version in `README.md`.

Entries are newest first.

---

## 2.0.0 — 2026-10-27

- **Report modes by file count.** 1 file → one full Individual Report; 2–5 → summary
  plus full reports; 6+ → summary plus compact reports, with a follow-up offer of
  the full report for chosen files. *Why:* long runs did not fit in one reply.
- **One pass, no pausing.** Parallel batches of up to 4 are kept, only progress
  lines are printed, and each `/importBI` answer is reduced to a short digest.
  *Why:* bulk runs stopped and asked the user to reply "continue".
- **Per-file and portfolio automation tables.** The summary now has Per-Workbook
  Automation, a Portfolio Automation Summary (all files, excluding outliers,
  per-file median), and outliers shown separately. *Why:* a pooled rate let one file
  skew the rate for every file.
- **Uplift mandatory everywhere.** The patterns repo is read once per run, every
  header shows whether it was read, and the summary has its own Uplift section.
  When nothing matches, the section is a single "no uplift" line. Uplift (pp) is
  defined per row.
- **New counting rules:**
  - display & gating calcs (gating calcs are still assessed);
  - Auto % vs Auto with review %;
  - root 🔧 calcs and their dependents;
  - the calculation families are now required names everywhere;
  - shared data sources counted once, including a `.tdsx` assessed together with
    the workbooks that use it;
  - no unused exclusion for `.tds` / `.tdsx` files or shared data sources;
  - layer rates.
- **Complexity rating** is now a points score built from the previous High
  criteria, plus calc depth and user filters.
- **🔧 Manual Adjustment Report** is organised by root 🔧 calcs and uses the same
  format whether requested up front or later.
- **Headings aligned:** each report starts with its own `#` title. Line limits are
  now ≤ 300 per full report, ≤ 25 per compact report, and ≤ 150 for the summary.
- **Skill text consolidated** into one Rules list. The Tableau-specific rules are
  unchanged and each is now stated once.

---

## 1.1.0 — 2026-10-12

- Review feedback (parity with the Power BI skill) and reviewer suggestions.

---

## 1.0.0 — 2026-10-05

- Initial release.
