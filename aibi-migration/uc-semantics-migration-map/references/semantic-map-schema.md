# semantic-map.yaml — the desired state

Every object kind is a list of objects with a stable `key`. Kinds: `domains`, `concepts`, `metric_views`, `pages`, `wikis`, `asset_tags`
(plus a read-only `report_map`). Common fields:

| Field | Meaning |
|-------|---------|
| `key` | Identity, derived from evidence (`dom-<fact table>`, `cn-<fact>-<metric>`, `mv-…`, `pg-…`, `wk-…`). **Never edit.** |
| `source` | `derived` (regenerated on refresh, except pinned fields) · `manual` (yours; never touched) |
| `pinned` | Fields a human changed — refreshes never overwrite them (auto-detected for hand edits in the yaml) |
| `approval` | `proposed` → `approved` / `rejected` |
| `approved_hash` | Hash of the spec when approved. If it no longer matches, apply skips the object (*changed since approval*) |
| `status` | `orphaned` = no longer supported by the inputs; kept, not applied |
| `blockers` | Computed; e.g. *set target.catalog*, *no concepts left* |

Per kind (**bold** = part of the approved *spec*):

- **domains** — **`tag_key`**, **`parent`**, `name` (display; UI-only), **`subtitle`**, **`description`**, `evidence`
- **concepts** — **`name`**, **`domain`**, **`mv`** (the metric-view shell that will own it), `fact_table`, `variants` `[{formula, sql_hint, reports}]`
  (every distinct definition found), `reports`, `drift`, `need` (high/medium/low), `patterns` (hints into uc-semantics-patterns),
  **`definition`** (business wording, optional), **`chosen`** (the winning variant's formula text — required to settle drift)
- **metric_views** (shells) — **`fqn`**, **`source_table`**, **`comment`**, **`concepts`** (keys), **`concept_hash`** (hash of the decisions the YAML must honour),
  `title`, `grain`, `purpose`, `time_dimension`, `long_tail` (one-off metrics left in their reports), `patterns`, `absorbs`.
  Stage-2 fields (not part of the shell approval): `yaml` (authored Metric View YAML), `yaml_origin` (`agent-drafted`|`manual`),
  `yaml_approved_hash`, `yaml_concept_hash`; `authoring` is computed: `pending` → `drafted (awaiting approval)` → `approved`, or `STALE`
  when a concept decision changed after the YAML was written.
- **pages** — **`domain`** (a domain key or `general`), **`title`**, **`synonyms`**, **`description`** (≤280), **`body`** (markdown), **`related`**, **`sources`**
- **wikis** — **`table`** (UC fqn), **`body`**
- **asset_tags** — **`securable`**, **`name`** (fqn), **`tag_key`**, **`tag_value`**, `domain`

Hand edits: change a derived scalar (`name`, `subtitle`, `description`, `title`, `purpose`, `body` …) in the yaml and the next `design.py`
run detects it (it remembers a hash of what it generated, `_gen`) and pins it. Prefer `decide.py set`. To restructure beyond what the
report offers (move a metric view to another domain, add a subdomain, add a page), add the object with `source: manual` — manual objects
are never regenerated or removed.
