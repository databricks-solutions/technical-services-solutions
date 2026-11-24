---
name: uc-semantics-migration-map
description: Build a Unity Catalog semantic foundation from a customer's BI estate (Tableau / Power BI files, a live Tableau or Power BI MCP connection, plus any documentation). STAGE 1 (Assessment, read-only) finds the concepts that need consolidation — metrics like Net Revenue used by many reports or defined several ways — and proposes Domains/Subdomains, Metric View shells, Pages and Wikis in a friendly HTML report plus a chat review. STAGE 2 (Implementation) authors each Metric View's YAML against the real tables following the live uc-semantics-patterns repo, validates it on the workspace, and creates only what the user approved — idempotently. Re-run the assessment any time with new inputs; decisions survive. Use for 'consolidate our metrics into Unity Catalog', 'design domains and metric views', 'semantic layer migration from Tableau/Power BI', 'UC semantics migration map', 'apply the semantic map'.
user-invocable: true
---

# UC Semantics Migration Map

*Successor to `aibi-migration-map`.* That skill answers "what does each report become?". This one answers
**"what single, governed definition of each business concept should exist in Unity Catalog — and then builds it."**

```
 STAGE 1  ASSESSMENT (read-only)                          STAGE 2  IMPLEMENTATION (writes, only what is approved)
 inputs ─► ingest ─► design ─► report.html + chat review ─► author MV YAML ─► validate ─► approve ─► apply
 files/MCP/docs    concepts, shells, domains, pages        (agent, from real columns   (throw-away   (user)   plan → execute
                   NO metric-view YAML yet                  + live patterns repo)       view)                  re-run = no-op
```

## You are the operator

**A human converses with you; you run every command.** They never touch a terminal. So:

- Run the scripts yourself, summarise results in plain chat, and ask for decisions in chat
  (`decide.py` records them). The HTML report is the visual review aid — tell them where it is and what to look at.
- **Never run a write without an explicit go.** Plans, validation, reports and designs are free; `apply.py --execute`
  and `--prune` change the workspace/account — show the plan, name the workspace and what will change, get a clear yes first.
- Be honest about gaps: say what you could not translate, what is a draft, what needs a human with more privileges.
- Never invent definitions, columns or owners. Quote what the estate/documents actually say.

### How to run the scripts (read this once)

Inside a Databricks notebook / Genie Code the workspace credentials live in **your own Python process**; a child
process (`!python …`, `subprocess`) can't use them on serverless. So run the CLIs **in-process** with `ucsm.run`:

```python
import sys
SKILL = "/Workspace/Users/<me>/.assistant/skills/uc-semantics-migration-map"   # or /Workspace/.assistant/skills/…
sys.path.insert(0, SKILL + "/scripts")
import ucsm
ucsm.run("ingest.py", DIR, "-o", f"{DIR}/output/inventory.json", "--account", "Acme")   # prints output, returns exit code
rc, out, err = ucsm.run_captured("decide.py", "summary", f"{DIR}/output/semantic-map.yaml")   # capture instead
```

Everywhere below `X.py args` means `ucsm.run("X.py", args…)`. On a laptop/CI (not in Databricks) plain
`python3 scripts/X.py args` works too — add `--profile <cli-profile>` to `apply.py` / `author.py`.
Dependencies (`pyyaml`, `databricks-sdk`) are preinstalled on Databricks compute; otherwise `pip install pyyaml databricks-sdk`.
Auth is ambient in Databricks — never ask for or print tokens.

`<DIR>` is the analysis folder (a UC **Volume** path like `/Volumes/<cat>/<sch>/<vol>/acme/`, or a workspace folder).
Everything generated goes to `<DIR>/output/`. Always hand back `semantic-map.yaml` (the editable source of truth) **and** `report.html`.

## What gets designed

| Object | Seeded from | Written by |
|---|---|---|
| **Concept** — a metric needing one definition (used by ≥2 reports, or defined >1 way) | calculated fields / DAX measures; drift detected | not an object itself: it drives the next rows |
| **Domain / Subdomain** — business areas on governed tags | fact-table clusters (a schema shared by ≥2 fact tables → parent domain) | `apply.py` |
| **Metric View** (shell → YAML) — the one home for a set of concepts | one per fact table that has concepts | shell by `design.py`; **YAML by you in Stage 2** |
| **Page** — authoritative definition of a concept / glossary term | every concept + `glossary.yaml` terms | `apply.py` |
| **Wiki** — documentation of each Metric View's source table | fact tables | `apply.py` |
| **Domain tags** — bind each MV and source table into its domain | derived | `apply.py` |

One-off metrics used by a single report stay in their report (listed as "long tail"); pass `--include-singletons` to promote them.
It does **not** score effort, and does not migrate the reports themselves (that is `aibi-migration-map`).

## Stage 1 — Assessment

**1. Ask the user** (don't guess): where the inputs are (`<DIR>`), the customer name, and **the target catalog**
(and optionally schema for the Metric Views, default `semantic`; SQL warehouse is auto-picked). In a *shared account*,
also set a `--tag-prefix` (e.g. `acme`) so domain tags can't collide with other teams'.

**2. Ingest** — raw files are parsed structurally (never the data); live sources and documents are read by you:

```
ingest.py <DIR> -o <DIR>/output/inventory.json --account "<Customer>"
```
- `.twbx/.tdsx` (Tableau), `.pbit` (Power BI; best) and `.pbix` are parsed automatically. `.pbix`/live-connection reports are *thin*
  (no readable model) — tell the user which, and what to export to recover them.
- **Live MCP (Tableau / Power BI):** if such a server is connected, pull workbooks/datasets, their calculated fields / DAX measures,
  upstream tables and the date table — metadata only, no row data — and write `<DIR>/<name>.inventory.json`
  ([references/inventory-schema.md](references/inventory-schema.md)); `ingest.py` merges them.
- **Documentation / apps / wikis:** read what is relevant and distil **business terms** into `<DIR>/glossary.yaml`
  (`term, definition, synonyms, domain_hint, source`). Quote the document; don't paraphrase into new definitions.
- Optional `<DIR>/design.yaml` (see `examples/design.example.yaml`): `target.*`, and `table_map` (source-tool table → UC table).

**3. Design** (re-runnable):
```
design.py <DIR>/output/inventory.json -o <DIR>/output/semantic-map.yaml --catalog <cat> [--schema <sch>] [--tag-prefix <p>] [--config <DIR>/design.yaml]
render.py <DIR>/output/semantic-map.yaml -o <DIR>/output/report.html
```

**4. Review with the user — in chat.** Run `decide.py summary <map>` and explain it in plain language: how many reports,
which concepts are consolidated, **which drift** (and how), the proposed domains and Metric View shells, thin reports.
Point them at `report.html` (Concepts tab is the one to read). Then record their decisions:

| They say | You run |
|---|---|
| "Net Revenue should be the net-of-returns one" | `decide.py choose <map> <concept-key> <variant#>` (see `decide.py show` for the variants) |
| "Approve everything in Sales" / "looks good" | `decide.py approve <map> --kind … --keys …` / `--all` (use `--drift-free` to leave undecided drift alone) |
| "Rename the Retail domain" / "that's not what Units means" | `decide.py set <map> <kind> <key> name="…"` |
| "Drop the Customer Orders domain" | `decide.py reject <map> --kind domains --keys …` |
| they downloaded `decisions.json` from the report | `decide.py import <map> <file>` |

A drifting concept needs a decision before its Metric View can be authored — **never pick the winner yourself**.
If the target catalog is missing, objects show `blocked` until `design.py --catalog …` is re-run.

## Stage 2 — Implementation

Only start when the user has approved the shells and wants to proceed. It needs real privileges
([references/uc-objects.md](references/uc-objects.md)); if they lack them, give them the plan to hand to an admin.

### 2a · Author each Metric View's YAML (you, per approved shell)

```
author.py context  <map> <mv-key>          # JSON briefing: concepts + variants found, chosen definitions, the source table's REAL columns,
                                           # which patterns apply and the command to read each
patterns.py show "<pattern folder>" --yml  # read the relevant patterns from the LIVE uc-semantics-patterns repo before writing
author.py register <map> <mv-key> <file.yaml>   # static checks (columns exist, a measure per concept, version, …)
author.py validate <map> <mv-key>          # LIVE: creates it under a throw-away name, queries EVERY measure, drops it. Nothing real changes.
author.py approve  <map> <mv-key>          # only after the user has seen the YAML and said yes
```

Rules (the same ones `author.py context` prints):
- **Follow the patterns repo** (`github.com/databricks-solutions/uc-semantics-patterns`): window measures for period-over-period / YTD /
  moving windows, `semiadditive: last` for balances, calendars, currency, ranking, segmentation. Fetched live; falls back to a bundled
  index offline (`patterns.py index` says which source and commit it used).
- One measure per approved concept, **named exactly like the concept**; use the `chosen` / `definition` variant, never your own pick.
- Use only columns present in `source_columns`. If a needed column doesn't exist, **leave the measure out and tell the user** why.
- Don't translate what you can't translate faithfully (Tableau LOD / table calcs, complex DAX context). Say so; a view with fewer measures is fine.
- Fix every `validate` error. Then **show the user the YAML and a plain summary** (measures included, measures left out and why) and ask.
- Editing a drift decision later marks the YAML **STALE**; re-author and re-approve.

### 2b · Apply

```
apply.py <map> --plan-json <DIR>/output/apply-plan.json          # DRY RUN: live reads, zero writes
render.py <map> -o <DIR>/output/report.html --plan <DIR>/output/apply-plan.json
apply.py <map> --execute --yes [--publish] [--only metric_views,…]      # ONLY after the user's explicit go
apply.py <map>                                                    # again: must say "Nothing to write"
```
1. Summarise the plan in plain words: what will be created/updated, what is skipped and why, what needs admin help.
2. **Confirm** the workspace, the target catalog.schema, and whether Domains/Pages/Wikis should be **published** or stay **drafts** (default: drafts — invisible to consumers until a curator publishes; `--publish` flips them).
3. Execute, then re-run the plan: it must report nothing to do. Report failures verbatim.
4. Guarantees: only approved objects whose approval still matches their spec; a Metric View also needs its YAML approved; each YAML is
   validated on a throw-away view first so **a broken definition can never replace a good one**; nothing is deleted without `--prune`
   (and prune only touches what this tool created, recorded in `apply-state.json`); an existing object this tool didn't create is blocked unless `--adopt`.
5. After a Metric View is replaced its domain tags are re-applied automatically (`CREATE OR REPLACE` drops them).
6. If an API is unavailable on the workspace (Pages/Wikis/governed tags), the object is exported as markdown under `<DIR>/output/export/`
   (Pages can be bulk-imported with Genie Code) and listed as a manual step; everything else still applies.

**API limits to tell the user:** domain *display names* and Discover-page *sections* are UI-only; publishing drafts needs a curator
(or `--publish` with the right permission). Domains, governed tags and Pages are **account-level** — they are visible account-wide,
which is why a tag prefix matters in shared accounts.

## Refreshing (inputs changed, new reports, a new quarter)

Run `ingest → design → render` again with the same `<DIR>`. The merge is idempotent: same inputs give a byte-identical map; objects keep
their identity when renamed; anything a human edited stays pinned; approvals survive; things that disappear become `orphaned` (kept,
never auto-deleted); new concepts arrive as `proposed`. Then `author.py status <map>` shows which Metric Views need (re-)authoring and
`apply.py` shows exactly what changed. Do not recreate the map from scratch.

## Troubleshooting

| Symptom | Likely cause → action |
|---|---|
| `CONTEXT_UNAVAILABLE_FOR_REMOTE_CLIENT` / "credentials are not available to a child process" | You ran a script as a child process in a notebook. Use `ucsm.run(...)`. |
| `UNRESOLVED_COLUMN` in `author.py validate` | The YAML uses a column the source table doesn't have — check `source_columns`; for Tableau/PBI names, map to the UC column or drop the measure. |
| plan: `blocked: set target.catalog` | Re-run `design.py --catalog <cat>`. |
| plan: `skip … YAML not authored / not approved / STALE` | Do Stage 2a for that shell (or re-author after a drift decision changed). |
| plan: `skip … changed since approval` | Someone edited it after approval — review, then `decide.py approve`. |
| plan: `a domain on tag … already exists and was not created by this tool` | Another team's domain. Use `--tag-prefix`, or `--adopt` only if the user confirms it is theirs. |
| `PERMISSION_DENIED` on domains/pages | Needs `MANAGE DISCOVER` (account/workspace admins have it); governed tags need account admin. Hand over the plan. |
| `SQL … PERMISSION` / `USE SCHEMA` | Needs `CREATE TABLE` + `USE SCHEMA` on the target schema and `SELECT` on sources. |
| `.pbix` / thin report has no measures | Binary/live-connection model — export the dataset as `.pbit` (or `model.bim`) and re-ingest. |

## Verify the tooling (no workspace needed)

`python3 tests/test_idempotency.py` — 30+ checks of the whole contract against an in-memory client.
`tests/live_smoke.py --catalog <cat> [--account-objects] [--in-process]` — end-to-end against a real workspace (creates and removes a throw-away schema; `--account-objects` also creates and removes governed tags, domains, pages and wikis under a random prefix).

## Files

- `scripts/` — `ingest.py` · `design.py` · `decide.py` · `render.py` · `author.py` · `apply.py` · `patterns.py` · `ucsm.py` (in-process runner) · `smlib.py` · `dbx.py` · `adapters/` (Tableau/Power BI parsers shared with `aibi-migration-map`)
- `references/` — `inventory-schema.md` · `semantic-map-schema.md` · `uc-objects.md` (what each object is, the exact API each uses, privileges, limits) · `patterns-index.snapshot.json` (offline fallback index only)
- `examples/` — synthetic "Acme Retail": `inventory.example.json`, `design.example.yaml`, `semantic-map.example.yaml`, `example_report.html`
