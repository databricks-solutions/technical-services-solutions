# AI/BI Migration Map

Turn a raw Tableau or Power BI estate into a **single self-contained HTML migration map** — every
workbook routed to the Databricks AI/BI asset that replaces it (Lakeview dashboard, Genie space,
Databricks App, or SQL Alert), the mirror view (each asset and the workbooks it absorbs), and a
Metric View blueprint for the shared semantic layer.

It answers the two questions every BI migration starts with:

1. **What does each of my reports become on Databricks?**
2. **Where do the semantics live so answers stay consistent?**

The output is a **target design**, not a sizing estimate — it deliberately does not score migration
complexity, effort, or compatibility.

## User journey (in Databricks)

- **Install the skill.** Add a Git folder for `technical-services-solutions` under
  `/Workspace/Users/<your-email>/.assistant/`, enable **Sparse Checkout**, and set the cone pattern
  to `aibi-migration/aibi-migration-map` (pulls just this skill). See
  [Installing a skill](https://docs.databricks.com/aws/en/genie-code/skills).
- **Upload your estate.** Put your `.twbx`/`.tdsx` (Tableau) or `.pbit`/`.pbix` (Power BI) files in a
  Unity Catalog **Volume**.
- **Open Genie Code** anywhere in the workspace (new session).
- **Ask for the map:** *"Build a migration map for my `<Tableau | Power BI>` reports — files are in
  `<volume-path>`."* Add *"walk me through it interactively"* to review the grouping + routing before
  it renders.
- **Use the output.** The skill writes `mapping.yaml` + a self-contained `report.html`. Hand
  `report.html` to Genie Code as a conversion guide during `/importBI`.

## Quick start (local CLI)

```bash
pip install pyyaml

# 1 — parse raw files (point at a folder or a mounted Volume of exports)
python3 scripts/parse_twbx.py ~/estate_export/ -o ~/estate_export/output/mapping.yaml --account "Acme Retail"   # Tableau
python3 scripts/parse_pbit.py ~/estate_export/ -o ~/estate_export/output/mapping.yaml --account "Acme Retail"   # Power BI

# 2 — curate the mapping (rename groups to subject areas, name/consolidate assets,
#     refine Metric Views, mark duplicates RETIRE) — this is where the value is

# 3 — render to one shareable HTML file
python3 scripts/render.py ~/estate_export/output/mapping.yaml -o ~/estate_export/output/report.html
```

No raw files? Fill the hand-filled CSV template (`references/input-schema.md`) and run
`python3 scripts/route.py inventory.csv -o mapping.yaml` instead — same output, same next steps.

**See it first:** open [`examples/example_report.html`](examples/example_report.html) in a browser
for the exact output shape, and [`examples/mapping.example.yaml`](examples/mapping.example.yaml) for
the curated source that produced it (a fully synthetic "Acme Retail" estate).

## The routing rule (deterministic, first match wins)

| # | Condition | Becomes |
|---|-----------|---------|
| 1 | `params ≥ 3` and `n_calcs > 40` | **Databricks App** (a what-if / estimator tool) |
| 2 | purpose is error / exception / status / monitoring | **SQL Alert** |
| 3 | `text_pct ≥ 95%` and `datasources ≤ 2` | **Genie space** (a crosstab reader) |
| 4 | everything else | **Lakeview dashboard** |

Full rationale and tuning knobs: [`references/routing-rule.md`](references/routing-rule.md).

## Layout

```
aibi-migration-map/
├── SKILL.md                     # skill entry point (workflow, inputs, interactive mode)
├── README.md                    # this file
├── scripts/
│   ├── parse_twbx.py            # Tableau .twbx/.tdsx  → starter mapping.yaml
│   ├── parse_pbit.py            # Power BI .pbit/.pbix  → starter mapping.yaml
│   ├── parse_common.py          # shared parse helpers (metric detection, drift, fact/dim class)
│   ├── route.py                 # routing rule + mapping builder (+ hand-filled CSV entry point)
│   └── render.py                # curated mapping.yaml → single self-contained HTML
├── references/
│   ├── routing-rule.md          # the dashboard/Genie/App/Alert rule + rationale
│   └── input-schema.md          # every accepted input contract
├── templates/
│   └── report_template.html     # the report shell (inline CSS/JS, meta-driven)
└── examples/
    ├── mapping.example.yaml      # fully-curated synthetic mapping
    └── example_report.html       # the rendered example (open this first)
```

## Requirements

- **Python 3** with **`pyyaml`** (`pip install pyyaml`). Parsing otherwise uses only the standard
  library (`zipfile`, `xml.etree`).
- **A browser.** No auth, no network, no Databricks connection — the whole pipeline runs locally and
  the output is a static file.

## Privacy note

Raw `.twbx`/`.tdsx`/`.pbit` files embed real identifiers — account/brand names, DB hostnames and
catalogs, service-account usernames (occasionally access keys) in connection strings, and analyst
desktop paths. **Scrub these before reusing a real workbook as a shared example.** `parse_twbx.py`
reads only the `.twb` XML structure — it never opens the packaged `.hyper` data extract.
