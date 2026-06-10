"""
Dashboard validation for generated .lvdash.json files.

Performs structural checks (widget versions, field name consistency,
dataset references, grid layout), SQL execution checks (runs each
dataset query against the warehouse with LIMIT 1), and layout fidelity
checks (page count, visual coverage, position accuracy vs. PBI source).
"""

from dataclasses import dataclass, field
from typing import Optional

from databricks.sdk import WorkspaceClient

from clients import VALID_WIDGET_VERSIONS, GRID_COLUMNS


@dataclass
class LayoutFidelityResult:
    """Results of comparing the generated dashboard layout against the PBI source."""
    page_count_match: bool = True
    expected_pages: int = 0
    actual_pages: int = 0
    missing_visuals: list = field(default_factory=list)
    extra_pages: list = field(default_factory=list)
    missing_pages: list = field(default_factory=list)
    position_warnings: list = field(default_factory=list)
    page_visual_counts: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.page_count_match and not self.missing_visuals

    @property
    def summary_lines(self) -> list:
        lines = []
        if self.page_count_match:
            lines.append(f"Page count: {self.actual_pages} canvas page(s) — matches PBI ({self.expected_pages})")
        else:
            lines.append(
                f"Page count MISMATCH: expected {self.expected_pages} canvas page(s), "
                f"got {self.actual_pages}"
            )
        for entry in self.page_visual_counts:
            lines.append(
                f"Page \"{entry['name']}\": {entry['actual']} widget(s) — "
                f"expected {entry['expected']} from PBI"
            )
        if self.missing_visuals:
            lines.append(f"{len(self.missing_visuals)} visual(s) from PBI not found in dashboard")
        if self.position_warnings:
            lines.append(f"{len(self.position_warnings)} widget(s) with position drift")
        return lines


@dataclass
class TableCoverageResult:
    """Results of checking whether all PBI semantic model tables appear in dashboard SQL."""
    pbi_tables: list = field(default_factory=list)  # [{"pbi_table", "source_fqn", "table_type"}]
    queried_tables: list = field(default_factory=list)  # [{"pbi_table", "source_fqn", "found_in_datasets": [...]}]
    missing_tables: list = field(default_factory=list)  # [{"pbi_table", "source_fqn"}]
    calculated_tables: list = field(default_factory=list)  # [{"pbi_table", "source_fqn"}]
    internal_tables: list = field(default_factory=list)  # [{"pbi_table", "source_fqn"}]

    @property
    def passed(self) -> bool:
        return not self.missing_tables

    @property
    def coverage_pct(self) -> float:
        physical = [t for t in self.pbi_tables if t.get("table_type") == "physical"]
        if not physical:
            return 100.0
        return len(self.queried_tables) / len(physical) * 100


@dataclass
class ValidationResult:
    """Collects validation errors and warnings for a dashboard JSON."""
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    sql_results: list = field(default_factory=list)
    layout_fidelity: Optional[LayoutFidelityResult] = None
    table_coverage: Optional[TableCoverageResult] = None

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    @property
    def total_issues(self) -> int:
        return len(self.errors) + len(self.warnings)


def _get_dataset_sql(ds: dict) -> str:
    """Extract the SQL string from a dataset, handling both queryLines (array) and query (string) formats."""
    if "queryLines" in ds:
        return " ".join(ds["queryLines"])
    return ds.get("query", "")


def _extract_fqn_tables(sql: str) -> list[str]:
    """Extract fully-qualified table names (catalog.schema.table) from a SQL query."""
    try:
        import sqlglot
        from sqlglot import exp as E
        tree = sqlglot.parse_one(sql, dialect="spark")
        tables = []
        for table in tree.find_all(E.Table):
            parts = []
            if table.catalog:
                parts.append(table.catalog)
            if table.db:
                parts.append(table.db)
            parts.append(table.name)
            if len(parts) >= 2:
                tables.append(".".join(parts))
        return tables
    except Exception:
        return []


def _describe_table(sp_client, warehouse_id: str, fqn: str) -> list[str] | None:
    """Return column names for a UC table, or None on failure."""
    try:
        from databricks.sdk.service.sql import StatementState
        stmt = sp_client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=f"DESCRIBE TABLE {fqn}",
            wait_timeout="15s",
        )
        if stmt.status and stmt.status.state == StatementState.SUCCEEDED:
            return [
                row[0] for row in (stmt.result.data_array or [])
                if row and row[0] and not row[0].startswith("#")
            ]
    except Exception:
        pass
    return None


def _extract_column_refs(expression: str) -> set[str]:
    """Extract backtick-quoted column references from a widget expression."""
    import re
    return set(re.findall(r"`([^`]+)`", expression))


def validate_dashboard(dashboard_json: dict, warehouse_id: str, sp_client: WorkspaceClient) -> ValidationResult:
    """Validate the generated .lvdash.json for structural correctness and SQL validity.

    Structural checks:
      - Required top-level keys (datasets, pages)
      - Every dataset has a non-empty SQL query
      - Widget versions match the spec (counter=2, bar/line/pie=3, etc.)
      - Field names in widget.queries[].query.fields match spec.encodings fieldNames
      - Every widget's datasetName references an existing dataset
      - Layout grid: widget widths are within 1-6
      - Text widgets use multilineTextboxSpec without a spec block

    SQL checks:
      - Execute each dataset query with LIMIT 1 against the warehouse
    """
    result = ValidationResult()
    datasets = dashboard_json.get("datasets", [])
    pages = dashboard_json.get("pages", [])

    if not datasets:
        result.errors.append("Missing `datasets` — dashboard has no data sources.")
    if not pages:
        result.errors.append("Missing `pages` — dashboard has no pages.")

    # --- Dataset validation + SQL execution ---
    dataset_names = set()
    dataset_columns: dict[str, set[str]] = {}

    for ds in datasets:
        ds_name = ds.get("name", "<unnamed>")
        dataset_names.add(ds_name)

        if not ds.get("displayName"):
            result.warnings.append(f"Dataset `{ds_name}`: missing `displayName`.")

        query_str = _get_dataset_sql(ds)
        if not query_str.strip():
            result.errors.append(f"Dataset `{ds_name}`: empty SQL query.")
            result.sql_results.append((ds_name, False, "Empty query", []))
            continue

        try:
            from databricks.sdk.service.sql import StatementState
            stmt = sp_client.statement_execution.execute_statement(
                warehouse_id=warehouse_id,
                statement=f"SELECT * FROM ({query_str}) AS _t LIMIT 1",
                wait_timeout="30s",
            )
            if stmt.status and stmt.status.state == StatementState.SUCCEEDED:
                cols = [c.name for c in (stmt.manifest.schema.columns or [])] if stmt.manifest and stmt.manifest.schema else []
                result.sql_results.append((ds_name, True, None, cols))
                dataset_columns[ds_name] = set(cols)
            else:
                error_msg = stmt.status.error.message if stmt.status and stmt.status.error else "Unknown error"
                result.errors.append(f"Dataset `{ds_name}`: SQL query failed — {error_msg}")
                result.sql_results.append((ds_name, False, error_msg, []))

                for fqn in _extract_fqn_tables(query_str):
                    table_cols = _describe_table(sp_client, warehouse_id, fqn)
                    if table_cols:
                        result.errors.append(
                            f"  ↳ Table `{fqn}` available columns: {', '.join(table_cols)}"
                        )

        except Exception as e:
            result.errors.append(f"Dataset `{ds_name}`: SQL execution error — {e}")
            result.sql_results.append((ds_name, False, str(e), []))

    # --- Page & widget validation ---
    for page in pages:
        page_name = page.get("displayName", page.get("name", "<unnamed>"))
        page_type = page.get("pageType", "")
        layout = page.get("layout", [])

        if not page_type:
            result.warnings.append(f"Page `{page_name}`: missing `pageType`.")

        for item in layout:
            widget = item.get("widget", {})
            position = item.get("position", {})
            w_name = widget.get("name", "<unnamed>")

            # --- Text widgets ---
            if "multilineTextboxSpec" in widget:
                if "spec" in widget:
                    result.warnings.append(
                        f"Text widget `{w_name}` on `{page_name}`: has both `multilineTextboxSpec` and `spec` — remove `spec`."
                    )
                lines = widget["multilineTextboxSpec"].get("lines", [])
                if not lines:
                    result.warnings.append(f"Text widget `{w_name}` on `{page_name}`: empty `lines` array.")
                continue

            # --- Data widgets ---
            spec = widget.get("spec", {})
            widget_queries = widget.get("queries", [])

            if not spec and not widget_queries:
                result.warnings.append(f"Widget `{w_name}` on `{page_name}`: has no `spec` and no `queries`.")
                continue

            widget_type = spec.get("widgetType", "")
            version = spec.get("version", None)

            # Version check
            if widget_type in VALID_WIDGET_VERSIONS:
                expected = VALID_WIDGET_VERSIONS[widget_type]
                if version != expected:
                    result.errors.append(
                        f"Widget `{w_name}` on `{page_name}`: `{widget_type}` requires version {expected}, found {version}."
                    )
            elif widget_type and widget_type not in VALID_WIDGET_VERSIONS:
                result.warnings.append(
                    f"Widget `{w_name}` on `{page_name}`: unrecognized widgetType `{widget_type}`."
                )

            # Collect field names from widget.queries[].query.fields
            query_field_names = set()
            referenced_datasets = set()
            for wq in widget_queries:
                query_obj = wq.get("query", {})
                ds_ref = query_obj.get("datasetName", "")
                if ds_ref:
                    referenced_datasets.add(ds_ref)
                for f in query_obj.get("fields", []):
                    fname = f.get("name", "")
                    if fname:
                        query_field_names.add(fname)

                    # Check that columns in expression exist in dataset result
                    expr = f.get("expression", "")
                    if ds_ref and ds_ref in dataset_columns and expr:
                        ds_cols = dataset_columns[ds_ref]
                        for ref_col in _extract_column_refs(expr):
                            if ref_col not in ds_cols:
                                result.errors.append(
                                    f"Widget `{w_name}` on `{page_name}`: expression `{expr}` "
                                    f"references column `{ref_col}` not found in dataset `{ds_ref}` "
                                    f"(available: {', '.join(sorted(ds_cols))})"
                                )

            # Dataset reference check
            for ds_ref in referenced_datasets:
                if ds_ref not in dataset_names:
                    result.errors.append(
                        f"Widget `{w_name}` on `{page_name}`: references dataset `{ds_ref}` which doesn't exist."
                    )

            # Field name matching: encoding fieldNames must exist in query.fields
            encodings = spec.get("encodings", {})
            encoding_field_names = set()
            for enc_key, enc_val in encodings.items():
                if isinstance(enc_val, list):
                    for enc_item in enc_val:
                        if isinstance(enc_item, dict):
                            fn = enc_item.get("fieldName", "")
                            if fn:
                                encoding_field_names.add(fn)
                elif isinstance(enc_val, dict):
                    fn = enc_val.get("fieldName", "")
                    if fn:
                        encoding_field_names.add(fn)

            if query_field_names and encoding_field_names:
                unmatched = encoding_field_names - query_field_names
                if unmatched:
                    result.errors.append(
                        f"Widget `{w_name}` on `{page_name}`: encoding fieldName(s) {unmatched} not found in query fields {query_field_names}."
                    )

            # Grid layout check
            w = position.get("width", 0)
            if w < 1 or w > GRID_COLUMNS:
                result.warnings.append(
                    f"Widget `{w_name}` on `{page_name}`: width={w} is outside the 1–{GRID_COLUMNS} range."
                )

    return result


# ---------------------------------------------------------------------------
# Layout Fidelity Validation
# ---------------------------------------------------------------------------

PBI_TO_AIBI_TYPE_MAP = {
    "card": {"counter"},
    "multiRowCard": {"counter", "table"},
    "kpi": {"counter"},
    "textbox": {"text"},
    "lineChart": {"line"},
    "barChart": {"bar"},
    "clusteredBarChart": {"bar"},
    "stackedBarChart": {"bar"},
    "columnChart": {"bar"},
    "clusteredColumnChart": {"bar"},
    "stackedColumnChart": {"bar"},
    "donutChart": {"pie"},
    "pieChart": {"pie"},
    "pivotTable": {"table"},
    "table": {"table"},
    "areaChart": {"area", "line"},
    "stackedAreaChart": {"area", "line"},
    "scatterChart": {"scatter"},
    "treemap": {"bar", "pie"},
    "funnel": {"bar"},
    "gauge": {"counter"},
    "waterfallChart": {"bar"},
    "slicer": {"filter-multi-select", "filter-single-select", "filter-date-range-picker"},
}


def _get_widget_type(widget: dict) -> str:
    """Return the semantic type of an AIBI widget ('text', or the widgetType from spec)."""
    if "multilineTextboxSpec" in widget:
        return "text"
    return widget.get("spec", {}).get("widgetType", "unknown")


def _is_filter_widget(widget: dict) -> bool:
    wt = _get_widget_type(widget)
    return wt.startswith("filter-")


def validate_layout_fidelity(dashboard_json: dict, pbi_layout) -> LayoutFidelityResult:
    """Compare the generated dashboard against the parsed PBI layout.

    Checks:
      - Canvas page count matches PBI tab count
      - Each PBI page name has a corresponding AIBI page
      - All non-decorative PBI visuals are represented (including page-level slicers)
      - Widget grid positions approximate the PBI source positions
    """
    result = LayoutFidelityResult()
    pages = dashboard_json.get("pages", [])

    canvas_pages = [p for p in pages if p.get("pageType") != "PAGE_TYPE_GLOBAL_FILTERS"]

    result.expected_pages = pbi_layout.total_canvas_pages
    result.actual_pages = len(canvas_pages)
    result.page_count_match = result.expected_pages == result.actual_pages

    if result.actual_pages > result.expected_pages:
        result.extra_pages = [
            p.get("displayName", p.get("name", "?")) for p in canvas_pages[result.expected_pages:]
        ]
    elif result.actual_pages < result.expected_pages:
        aibi_names_lower = {
            (p.get("displayName") or p.get("name", "")).lower() for p in canvas_pages
        }
        for pbi_page in pbi_layout.pages:
            if pbi_page.display_name.lower() not in aibi_names_lower:
                result.missing_pages.append(pbi_page.display_name)

    for pbi_page_idx, pbi_page in enumerate(pbi_layout.pages):
        aibi_page = None
        pbi_name_lower = pbi_page.display_name.lower()
        for cp in canvas_pages:
            cp_name = (cp.get("displayName") or cp.get("name", "")).lower()
            if cp_name == pbi_name_lower:
                aibi_page = cp
                break
        if aibi_page is None and pbi_page_idx < len(canvas_pages):
            aibi_page = canvas_pages[pbi_page_idx]

        pbi_expected_on_page = list(pbi_page.data_visuals) + list(pbi_page.page_slicers)

        if aibi_page is None:
            for v in pbi_expected_on_page:
                result.missing_visuals.append({
                    "page": pbi_page.display_name,
                    "visual_type": v.visual_type,
                    "description": v.display_name or v.visual_id[:12],
                })
            continue

        layout_items = aibi_page.get("layout", [])
        aibi_non_text = [
            item for item in layout_items
            if _get_widget_type(item.get("widget", {})) != "text"
        ]

        pbi_non_text = [v for v in pbi_expected_on_page if v.visual_type != "textbox"]

        result.page_visual_counts.append({
            "name": pbi_page.display_name,
            "expected": len(pbi_non_text),
            "actual": len(aibi_non_text),
        })

        matched_aibi = set()
        for pbi_vis in pbi_non_text:
            expected_types = PBI_TO_AIBI_TYPE_MAP.get(pbi_vis.visual_type, set())
            best_match = None
            best_distance = float("inf")

            for idx, item in enumerate(aibi_non_text):
                if idx in matched_aibi:
                    continue
                w = item.get("widget", {})
                wt = _get_widget_type(w)
                pos = item.get("position", {})
                dx = abs(pos.get("x", 0) - pbi_vis.grid_x)
                dy = abs(pos.get("y", 0) - pbi_vis.grid_y)
                dist = dx + dy

                if wt in expected_types and dist < best_distance:
                    best_match = idx
                    best_distance = dist

            if best_match is not None:
                matched_aibi.add(best_match)
                item = aibi_non_text[best_match]
                pos = item.get("position", {})
                x_drift = abs(pos.get("x", 0) - pbi_vis.grid_x)
                w_drift = abs(pos.get("width", 1) - pbi_vis.grid_width)
                if x_drift > 1 or w_drift > 2:
                    result.position_warnings.append({
                        "page": pbi_page.display_name,
                        "visual_type": pbi_vis.visual_type,
                        "description": pbi_vis.display_name or pbi_vis.visual_id[:12],
                        "expected_x": pbi_vis.grid_x,
                        "expected_w": pbi_vis.grid_width,
                        "actual_x": pos.get("x", "?"),
                        "actual_w": pos.get("width", "?"),
                    })
            else:
                if not expected_types:
                    continue
                fallback_idx = None
                for idx, item in enumerate(aibi_non_text):
                    if idx not in matched_aibi and _get_widget_type(item.get("widget", {})) in expected_types:
                        fallback_idx = idx
                        break
                if fallback_idx is not None:
                    matched_aibi.add(fallback_idx)
                    continue
                result.missing_visuals.append({
                    "page": pbi_page.display_name,
                    "visual_type": pbi_vis.visual_type,
                    "description": pbi_vis.display_name or pbi_vis.visual_id[:12],
                })

    return result


# ---------------------------------------------------------------------------
# Table Coverage Validation
# ---------------------------------------------------------------------------


def validate_table_coverage(dashboard_json: dict, pbi_source_tables: list[dict]) -> TableCoverageResult:
    """Check that every PBI semantic model table is referenced in the dashboard SQL.

    Tables are classified by type:
      - "physical": checked against dashboard SQL for coverage
      - "calculated": reported separately (their DAX logic is translated to SQL
        using the underlying physical tables, so the calculated table name won't
        appear literally in the SQL)
      - "internal": PBI auto-generated tables (LocalDateTable_, DateTableTemplate_)
        that are excluded from coverage checks
    """
    result = TableCoverageResult(pbi_tables=list(pbi_source_tables))
    datasets = dashboard_json.get("datasets", [])

    dataset_sql: list[tuple[str, str]] = []
    for ds in datasets:
        ds_name = ds.get("name", ds.get("displayName", "<unnamed>"))
        sql = _get_dataset_sql(ds).lower()
        dataset_sql.append((ds_name, sql))

    for tbl in pbi_source_tables:
        table_type = tbl.get("table_type", "physical")

        if table_type == "internal":
            result.internal_tables.append({
                "pbi_table": tbl["pbi_table"],
                "source_fqn": tbl["source_fqn"],
            })
            continue

        if table_type == "calculated":
            result.calculated_tables.append({
                "pbi_table": tbl["pbi_table"],
                "source_fqn": tbl["source_fqn"],
            })
            continue

        fqn = tbl["source_fqn"].lower()
        short_name = tbl["pbi_table"].lower()

        found_in = []
        for ds_name, sql in dataset_sql:
            if fqn in sql or short_name in sql:
                found_in.append(ds_name)

        if found_in:
            result.queried_tables.append({
                "pbi_table": tbl["pbi_table"],
                "source_fqn": tbl["source_fqn"],
                "found_in_datasets": found_in,
            })
        else:
            result.missing_tables.append({
                "pbi_table": tbl["pbi_table"],
                "source_fqn": tbl["source_fqn"],
            })

    return result
