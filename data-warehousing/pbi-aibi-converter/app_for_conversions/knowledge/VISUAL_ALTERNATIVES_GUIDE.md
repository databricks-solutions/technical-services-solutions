# Visual Alternatives Guide (for unmapped PBI visuals)

This guide is used by the `alternatives.py` module when a PBI visual has no
direct AI/BI widget mapping, or the primary conversion did not emit an
equivalent widget. It describes acceptable fallbacks, required explicit
style attributes, and example widget JSON shapes.

## General rules

- Each alternative must be a COMPLETE AI/BI widget dict (ready to drop
  into a page's `layout[].widget`).
- Every alternative MUST include an `attributes` object with explicit,
  numeric style values: `font_size_px` (int), `title_font_size_px` (int),
  `grid_width` (1..6 int), `grid_height` (int >= 2), `palette` (list of
  hex colors), `primary_color` (hex), `title` (str), `show_legend` (bool),
  `show_title` (bool).
- Field names must match between `fields[].name` and `encodings.*.fieldName`.
- Version numbers: `counter`, `table`, `filter-*` = 2. `bar`, `line`,
  `pie`, `area`, `scatter` = 3. Text widgets use `multilineTextboxSpec`
  with no `spec` block.
- Never invent columns — only use columns that appear in the dataset
  preview supplied in the user prompt.

## PBI visual type → recommended alternative families

### `map`, `filledMap`, `shapeMap`, `azureMap`

AI/BI has no map widget. Offer, in order:

1. `table` grouping by the location field with aggregated metrics.
2. `bar` chart: x = location, y = metric, sorted descending.
3. A `counter` of the top location's value, with a short `text` caption
   describing the geography that was dropped.

### `gauge`, `kpi` (with trend), `multiRowCard`

Offer:

1. `counter` with explicit formatting (primary_color, title_font_size_px).
2. `table` showing the KPI alongside its target / prior value.
3. `bar` with two series (actual vs target) if both columns are present.

### `decompositionTree`, `qnaVisual`, `aiNarratives`

These are AI-driven PBI visuals. Offer:

1. `table` showing the measure broken down by the first candidate
   dimension.
2. `bar` for the same breakdown.
3. `text` widget summarizing what the original visual intended, using
   `multilineTextboxSpec` markdown.

### `ribbonChart`, `funnel`, `waterfallChart`, `treemap`

Offer:

1. `bar` (stacked if ribbon/waterfall) with the category on one axis.
2. `line` if the data has a temporal dimension.
3. `pie` only if the dimension has ≤ 8 distinct values.

### Custom visuals (anything starting with `PBIVizHandler` or unknown type)

Offer:

1. `table` dump of the relevant fields.
2. `bar` if there's exactly one categorical + one numeric field.
3. A `text` placeholder documenting the unsupported custom visual.

## Attribute stamping

Attributes land in the widget like this (consumed by
`apply_attributes_to_widget`):

- `title` → `spec.frame.title`
- `show_title` → `spec.frame.showTitle`
- `title_font_size_px` → `spec.frame.titleFont.size`
- `palette` → `spec.encodings.color.scale.range`
- `primary_color` → `spec.encodings.{y|value|angle}.scale.range[0]`
- Text widgets: if `title` is set and the first line isn't a heading,
  a `### {title}` heading is prepended.

## Minimal example (map → bar)

```json
{
  "label": "Revenue by region (bar)",
  "rationale": "AI/BI has no map; a sorted bar chart preserves the geographic comparison.",
  "widget": {
    "name": "fallback-map-by-region",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "sales_overview",
        "fields": [
          {"name": "region", "expression": "`region`"},
          {"name": "sum(revenue)", "expression": "SUM(`revenue`)"}
        ],
        "disaggregated": false
      }
    }],
    "spec": {
      "version": 3,
      "widgetType": "bar",
      "encodings": {
        "x": {"fieldName": "region", "scale": {"type": "categorical"}, "displayName": "Region"},
        "y": {"fieldName": "sum(revenue)", "scale": {"type": "quantitative"}, "displayName": "Revenue"}
      },
      "frame": {"showTitle": true, "title": "Revenue by Region"}
    }
  },
  "attributes": {
    "font_size_px": 14,
    "title_font_size_px": 18,
    "title": "Revenue by Region",
    "primary_color": "#118DFF",
    "palette": ["#118DFF", "#12239E", "#E66C37"],
    "grid_width": 4,
    "grid_height": 5,
    "show_legend": false,
    "show_title": true
  }
}
```
