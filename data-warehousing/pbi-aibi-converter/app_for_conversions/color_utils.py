"""
Color handling for the preview stage.

Ported verbatim from the `color-pbi-cursor` app's `color_utils_v2.py` so this
app's brand-color-preservation behaviour matches that one. The existing
`apply_brand_colors` in converter.py handles colors extracted from the PBI
file; this module handles the *user override* path and also normalises the
rendered JSON to work around AI/BI rendering quirks.

Rules (match observed AI/BI rendering behaviour):

  * Pie charts:     write `mark.colors` (scale.colors is not honoured).
  * Categorical:    query the warehouse for distinct values and build
                    `scale.mappings = [{value, color}, ...]`. If existing
                    mappings are present, just recolour them in order.
  * Quantitative:   `scale.colors = [first]`, remove any mappings.
  * No encoding:    fall back to `mark.colors`, or add a minimal
                    quantitative `encodings.color` for scatter.

`mark.colors` is also set as a positional fallback so that charts with odd
schemas still pick up something reasonable.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger("pbi_aibi_converter.color_utils")

CHART_TYPES = {"bar", "line", "pie", "area", "scatter"}

# Backtick-quoted SQL identifiers per Databricks SQL grammar may contain
# any unicode character EXCEPT a backtick (which is escaped as ``). For
# safety we accept only the conservative ASCII identifier set below; any
# other character is refused before being interpolated into a SELECT
# statement. This prevents a LLM-emitted `field` like
# `country` UNION SELECT password FROM secrets --` from breaking the
# subquery.
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z0-9_ ]+$")


def _quote_ident(name: str) -> str:
    """Backtick-quote an identifier, refusing anything that doesn't pass
    the conservative safe-identifier filter. Raises ValueError on refusal
    so callers see the bad input instead of silently producing []."""
    if not isinstance(name, str) or not _SAFE_IDENT_RE.match(name):
        raise ValueError(f"refusing to quote unsafe SQL identifier: {name!r}")
    return f"`{name}`"


def _fetch_distinct_values(
    sp_client, warehouse_id: str, sql: str, field: str, limit: int = 100
) -> list:
    """Run a DISTINCT query and return the unique values for a categorical field.

    `field` is treated as untrusted (it originates from LLM-emitted
    encodings and PBI source files) and is validated by `_quote_ident`
    before being interpolated. `sql` is treated as an opaque subquery —
    we never try to inspect or rewrite it, only embed it inside
    `SELECT ... FROM (sql)`. `limit` is forced to a small int.
    """
    try:
        quoted = _quote_ident(field)
    except ValueError as e:
        logger.warning("_fetch_distinct_values: %s", e)
        return []
    try:
        limit_int = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit_int = 100
    try:
        result = sp_client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=(
                f"SELECT DISTINCT {quoted} FROM ({sql}) AS _ds "
                f"WHERE {quoted} IS NOT NULL ORDER BY 1 LIMIT {limit_int}"
            ),
            wait_timeout="30s",
        )
        state = (
            (result.status and result.status.state and result.status.state.value) or ""
        )
        if state in ("PENDING", "RUNNING"):
            stmt_id = result.statement_id
            for _ in range(10):
                time.sleep(3)
                result = sp_client.statement_execution.get_statement(
                    statement_id=stmt_id
                )
                state = (
                    (result.status and result.status.state and result.status.state.value)
                    or ""
                )
                if state not in ("PENDING", "RUNNING"):
                    break
        rows = (result.result and result.result.data_array) or []
        return [r[0] for r in rows if r and r[0] is not None]
    except Exception as e:
        logger.warning("distinct values fetch failed for field=%s: %s", field, e)
        return []


def _existing_widget_colors(spec: dict) -> list[str]:
    """Return the colors currently set on a widget (if any), in priority order."""
    enc_color = (spec.get("encodings") or {}).get("color") or {}
    scale = enc_color.get("scale") or {}
    if isinstance(scale, dict):
        if scale.get("mappings"):
            colors = [m.get("color") for m in scale["mappings"] if m.get("color")]
            if colors:
                return colors
        if scale.get("colors"):
            return list(scale["colors"])
    mark = spec.get("mark") or {}
    if mark.get("colors"):
        return list(mark["colors"])
    return []


def build_widget_color_map(
    dashboard_json: dict,
    pbi_colors_by_position: Optional[dict] = None,
) -> dict:
    """Return `{widget_name: {...}}` for every chart widget to drive the UI picker.

    Priority for default colors:
      1. PBI palette (keyed by grid position)
      2. Colors already present in the dashboard JSON
      3. Databricks default blue
    """
    pbi_colors_by_position = pbi_colors_by_position or {}
    result: dict = {}
    for page in dashboard_json.get("pages", []):
        for item in page.get("layout", []):
            w = item.get("widget", {})
            spec = w.get("spec", {}) or {}
            wtype = spec.get("widgetType", "")
            if wtype not in CHART_TYPES:
                continue
            name = w.get("name", "")
            pos = item.get("position", {})
            title = (spec.get("frame") or {}).get("title") or name

            key = (pos.get("x", -1), pos.get("y", -1))
            colors = list(pbi_colors_by_position.get(key) or [])
            if not colors:
                colors = _existing_widget_colors(spec)
            if not colors:
                colors = ["#077a9d"]

            enc_color = (spec.get("encodings") or {}).get("color")
            field_name = (
                enc_color.get("fieldName", "") if isinstance(enc_color, dict) else ""
            )
            scale = (enc_color or {}).get("scale") if isinstance(enc_color, dict) else None
            scale_type = (scale or {}).get("type", "categorical") if isinstance(scale, dict) else "categorical"

            result[name] = {
                "title": title,
                "widget_type": wtype,
                "colors": colors,
                "position": pos,
                "color_field": field_name,
                "scale_type": scale_type,
            }
    return result


def normalize_render_colors(
    dashboard_json: dict,
    sp_client: Any = None,
    warehouse_id: Optional[str] = None,
) -> dict:
    """Post-processing pass that makes AI/BI actually render the colors.

    AI/BI rendering quirks this fixes:

      1. **Pie charts** ignore both `encodings.color.scale.colors` AND
         `mark.colors`. The ONLY thing the pie renderer honours is
         `encodings.color.scale.mappings` — a list of explicit
         `{value, color}` pairs. If we have a `sp_client` + `warehouse_id`
         available, we query the dataset for DISTINCT values of the color
         field and build those mappings ourselves.

      2. Single-series **line / area / bar / scatter** with no
         `encodings.color` block only render a custom color when
         `mark.color` (singular) is set. If the converter wrote a
         `mark.colors` (plural) list, we also set `mark.color` to the first
         element so the renderer picks something up.
    """
    dataset_sql: dict[str, str] = {}
    for ds in dashboard_json.get("datasets", []):
        if ds.get("name"):
            dataset_sql[ds["name"]] = "".join(ds.get("queryLines", [])) or ds.get("query", "")

    for page in dashboard_json.get("pages", []):
        for item in page.get("layout", []):
            w = item.get("widget", {})
            spec = w.get("spec") or {}
            wtype = spec.get("widgetType", "")
            if wtype not in CHART_TYPES:
                continue

            enc = spec.get("encodings") or {}
            color_enc = enc.get("color") if isinstance(enc, dict) else None
            scale = (
                color_enc.get("scale")
                if isinstance(color_enc, dict)
                and isinstance(color_enc.get("scale"), dict)
                else {}
            )

            palette: list[str] = []
            if scale.get("mappings"):
                palette = [
                    m.get("color") for m in scale["mappings"] if m.get("color")
                ]
            if not palette and scale.get("colors"):
                palette = [c for c in scale["colors"] if c]
            mark = spec.get("mark") or {}
            if not palette and mark.get("colors"):
                palette = [c for c in mark["colors"] if c]
            if not palette and mark.get("color"):
                palette = [mark["color"]]

            if not palette:
                continue

            if wtype == "pie":
                spec.setdefault("mark", {})["colors"] = palette

                if (
                    isinstance(color_enc, dict)
                    and scale
                    and scale.get("type", "categorical") == "categorical"
                    and not scale.get("mappings")
                ):
                    field = color_enc.get("fieldName", "")
                    ds_name = (
                        (w.get("queries") or [{}])[0]
                        .get("query", {})
                        .get("datasetName", "")
                    )
                    sql = dataset_sql.get(ds_name, "")
                    values: list = []
                    if sp_client is not None and warehouse_id and sql and field:
                        values = _fetch_distinct_values(
                            sp_client, warehouse_id, sql, field
                        )
                    if values:
                        scale["mappings"] = [
                            {"value": str(v), "color": palette[i % len(palette)]}
                            for i, v in enumerate(values)
                        ]
                        scale.pop("colors", None)
                continue

            if not isinstance(color_enc, dict):
                mark_block = spec.setdefault("mark", {})
                mark_block["color"] = palette[0]
                mark_block["colors"] = palette

    return dashboard_json


def apply_color_overrides(
    dashboard_json: dict,
    overrides: dict,
    sp_client: Any = None,
    warehouse_id: Optional[str] = None,
) -> dict:
    """Apply user-picked colors to `dashboard_json` in-place and return it.

    `overrides`: `{widget_name: [hex, hex, ...]}` — one list per chart widget.
    """
    dataset_sql: dict[str, str] = {}
    for ds in dashboard_json.get("datasets", []):
        if ds.get("name"):
            dataset_sql[ds["name"]] = "".join(ds.get("queryLines", []))

    for page in dashboard_json.get("pages", []):
        for item in page.get("layout", []):
            w = item.get("widget", {})
            spec = w.get("spec") or {}
            name = w.get("name", "")
            wtype = spec.get("widgetType", "")
            if wtype not in CHART_TYPES or name not in overrides:
                continue
            colors = [c for c in overrides[name] if c]
            if not colors:
                continue

            encodings = spec.setdefault("encodings", {})
            color_enc = encodings.get("color")

            if wtype == "pie":
                if isinstance(color_enc, dict):
                    scale = color_enc.setdefault("scale", {})
                    if scale.get("mappings"):
                        for i, m in enumerate(scale["mappings"]):
                            m["color"] = colors[i % len(colors)]
                    else:
                        scale["colors"] = colors
                continue

            if not isinstance(color_enc, dict):
                if wtype in {"bar", "area", "line"}:
                    spec.setdefault("mark", {})["colors"] = colors
                else:
                    y_enc = encodings.get("y")
                    if isinstance(y_enc, dict) and y_enc.get("fieldName"):
                        encodings["color"] = {
                            "fieldName": y_enc["fieldName"],
                            "scale": {"type": "quantitative", "colors": [colors[0]]},
                            "displayName": y_enc.get("displayName", y_enc["fieldName"]),
                        }
                    else:
                        spec.setdefault("mark", {})["colors"] = colors
                continue

            scale = color_enc.setdefault("scale", {})
            scale_type = scale.get("type", "categorical")

            if scale_type == "quantitative":
                if wtype in {"bar", "area", "line"}:
                    encodings.pop("color", None)
                    spec.setdefault("mark", {})["color"] = colors[0]
                else:
                    scale["colors"] = [colors[0]]
                    scale.pop("mappings", None)
                continue

            field = color_enc.get("fieldName", "")
            ds_name = (
                (w.get("queries") or [{}])[0].get("query", {}).get("datasetName", "")
            )
            sql = dataset_sql.get(ds_name, "")

            existing = scale.get("mappings") or []
            if existing:
                for i, m in enumerate(existing):
                    m["color"] = colors[i % len(colors)]
                scale["mappings"] = existing
                scale.pop("colors", None)
                spec.setdefault("mark", {})["colors"] = colors
                continue

            values: list = []
            if sp_client is not None and warehouse_id and sql and field:
                values = _fetch_distinct_values(sp_client, warehouse_id, sql, field)

            if values:
                scale["mappings"] = [
                    {"value": str(v), "color": colors[i % len(colors)]}
                    for i, v in enumerate(values)
                ]
                scale.pop("colors", None)
            else:
                scale["colors"] = colors
                scale.pop("mappings", None)
            spec.setdefault("mark", {})["colors"] = colors

    normalize_render_colors(
        dashboard_json, sp_client=sp_client, warehouse_id=warehouse_id
    )
    return dashboard_json
