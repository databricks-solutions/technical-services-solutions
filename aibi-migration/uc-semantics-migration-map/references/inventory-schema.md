# inventory.json — the one contract between "any source" and the design

`design.py` reads only this. Raw-file parsing and live MCP pulls are just different ways to produce it.
To support a new source (Looker, Qlik, Cognos, a metrics spreadsheet…), emit this shape — nothing else changes.

Write live-source output to `<DIR>/<anything>.inventory.json`; `ingest.py` merges it with the parsed files.
Only `reports` is required. Be conservative: **metadata only, never row data.**

```jsonc
{
  "schema": 1,
  "account": "Acme Retail",
  "reports": [
    {
      "id": "tableau-sales_overview",     // stable, unique: <tool>-<slug(name)>
      "name": "Sales Overview",
      "tool": "tableau",                  // tableau | powerbi | looker | … (free text)
      "kind": "workbook",                 // workbook | pbit | pbix | dataset | dashboard …
      "fact_tables": ["retail_dm.dm_sales_fct"],  // the table(s) the report is built on; first wins.
                                          // schema-qualified preferred. A bare name is matched to a
                                          // qualified one from another tool when unambiguous.
      "tables": ["retail_dm.dm_sales_fct", "retail_dm.clndr"],
      "calendar": "retail_dm.clndr",      // conformed date table, if any
      "measures": [                       // calculated fields / DAX measures / metrics
        {"name": "Net Revenue", "formula": "SUM([net_amt])"}
      ],
      "pages": 3, "visuals": 12, "params": 0, "text_pct": 0.1,
      "source": "databricks",             // connector / source system label
      "thin": false,                      // true when no model could be read
      "note": ""                          // why thin / what to export
    }
  ],
  "glossary_terms": [                     // distilled by the agent from documentation
    {"term": "Active Customer", "definition": "…", "synonyms": ["AC"],
     "domain_hint": "Customer Orders", "source": "docs/kpi-glossary.pdf"}
  ],
  "documents": [{"path": "docs/kpi-glossary.pdf", "kind": "pdf"}],
  "physical_tables": []                   // reserved: UC tables + comments, for future table-level design
}
```

`glossary.yaml` (`terms:` list, same fields as `glossary_terms`) is merged too — easier to hand-edit.

Rules of thumb for live pulls:

- Group key = the **fact table**. If the MCP cannot expose upstream SQL/tables, set `fact_tables: []`
  and the report lands in an "ungrouped" bucket you can place by hand in `semantic-map.yaml`.
- Keep `formula` as the tool's own syntax — the translation to Databricks SQL happens later, visibly.
- Duplicate/forked reports (`(copy)`, `_v2`) are fine: they collapse onto the same metric names and show up as drift or folded duplicates.
