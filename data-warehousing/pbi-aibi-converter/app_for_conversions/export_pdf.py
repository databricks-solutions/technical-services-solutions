"""Minimal plain-text PDF export for conversion validation results.

Produces a compact 2-3 page A4 report using Helvetica and only ASCII
characters, dashes, and underscores.
"""

import re
from datetime import datetime

_UNICODE_MAP = {
    "\u2192": "->",  "\u2190": "<-",  "\u2194": "<->",
    "\u21d2": "=>",  "\u21d0": "<=",
    "\u2014": "--",  "\u2013": "-",   "\u2015": "--",
    "\u2010": "-",   "\u2011": "-",   "\u2012": "-",
    "\u2018": "'",   "\u2019": "'",
    "\u201c": '"',   "\u201d": '"',
    "\u2026": "...",
    "\u2022": "-",   "\u00b7": "-",
    "\u2265": ">=",  "\u2264": "<=",  "\u2260": "!=",
    "\u00d7": "x",   "\u00f7": "/",
    "\u2705": "[PASS]", "\u274c": "[FAIL]",
    "\u26a0\ufe0f": "[WARN]", "\u2139\ufe0f": "[INFO]",
    "\U0001f527": "[CALC]", "\u23ed\ufe0f": "[SKIP]",
    "\u26a0": "[WARN]", "\u2139": "[INFO]", "\u23ed": "[SKIP]",
}

_NON_ASCII_RE = re.compile(r"[^\x20-\x7E\n\r\t]")


def _ascii(text) -> str:
    """Force any value to printable ASCII."""
    text = str(text)
    for char, repl in _UNICODE_MAP.items():
        text = text.replace(char, repl)
    return _NON_ASCII_RE.sub("", text)


def build_export_pdf(
    report_name: str,
    model: str,
    workspace_path: str,
    dash_url: str,
    n_datasets: int,
    n_widgets: int,
    n_canvas: int,
    n_pages: int,
    layout_fidelity,
    explanation: str,
    validation,
    data_sources: list[dict],
    external_sources: list[dict],
    dashboard_json: dict,
    valid_widget_versions: dict,
) -> bytes:
    """Build a compact plain-text A4 PDF and return raw bytes."""
    from fpdf import FPDF

    W = 170  # usable text width (A4=210 minus 20mm margins each side)

    pdf = FPDF(format="A4")
    pdf.set_margins(20, 15, 20)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def heading(text):
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(W, 5, _ascii(text), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(100, 100, 100)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)

    def txt(text):
        pdf.multi_cell(W, 4, _ascii(text), new_x="LMARGIN", new_y="NEXT")

    def item(status, text):
        pdf.multi_cell(W, 4, _ascii(f"[{status}] {text}"), new_x="LMARGIN", new_y="NEXT")

    # ---- Title ----
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(W, 8, _ascii(report_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(W, 4, f"Validation Report -- {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(W, 4, _ascii(f"Model: {model}  |  Path: {workspace_path}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(W, 4, _ascii(dash_url), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # ---- Summary ----
    heading("Summary")
    n_filter = n_pages - n_canvas
    lf = layout_fidelity
    pg_info = f"{n_canvas} canvas" + (f" + {n_filter} filter" if n_filter else "")
    pg_match = ""
    if lf:
        pg_match = f"  |  PBI tabs: {lf.expected_pages} -> {lf.actual_pages} ({'match' if lf.page_count_match else 'MISMATCH'})"
    txt(f"Datasets: {n_datasets}  |  Widgets: {n_widgets}  |  Pages: {pg_info}{pg_match}")
    pdf.ln(1)

    # ---- Table Coverage ----
    tc = getattr(validation, "table_coverage", None)
    if tc:
        heading("Table Coverage")
        for tbl in tc.queried_tables:
            item("PASS", f"{tbl['pbi_table']}  ->  {tbl['source_fqn']}")
        for tbl in tc.missing_tables:
            item("SKIP", f"{tbl['pbi_table']}  ->  {tbl['source_fqn']}  (unused)")
        for tbl in tc.calculated_tables:
            item("CALC", f"{tbl['pbi_table']}  (DAX -> SQL)")
        for tbl in tc.internal_tables:
            item("SKIP", f"{tbl['pbi_table']}  (PBI auto-generated)")
        if external_sources:
            pdf.ln(1)
            item("WARN", f"{len(external_sources)} external source(s) need Databricks access")

    # ---- Layout Fidelity ----
    if lf:
        heading("Layout Fidelity")
        s = "PASS" if lf.page_count_match else "FAIL"
        item(s, f"Page count: {lf.actual_pages} canvas (expected {lf.expected_pages})")
        for entry in lf.page_visual_counts or []:
            ok = entry["actual"] >= entry["expected"]
            item("PASS" if ok else "WARN", f"{entry['name']}: {entry['actual']} widgets (expected {entry['expected']})")
        if lf.missing_visuals:
            item("FAIL", f"{len(lf.missing_visuals)} visual(s) missing:")
            for mv in lf.missing_visuals[:8]:
                txt(f"    - {mv['visual_type']} -- {mv['description']} (page: {mv['page']})")
        else:
            item("PASS", "All PBI visuals represented")

    # ---- SQL Validation ----
    if validation.sql_results:
        heading("SQL Validation")
        for ds_name, ok, err, cols in validation.sql_results:
            if ok:
                item("PASS", f"{ds_name} -- {len(cols)} cols")
            else:
                item("FAIL", f"{ds_name} -- {err}")

    # ---- Structural Checks ----
    heading("Structural Checks")
    if not validation.errors:
        item("PASS", "All widget versions correct")
        item("PASS", "All fieldNames match query columns")
        item("PASS", "All dataset references valid")
    else:
        for err in validation.errors[:12]:
            item("FAIL", str(err))
    if validation.warnings:
        pdf.ln(1)
        for warn in validation.warnings[:8]:
            item("WARN", str(warn))

    # ---- Conversion Notes (compact, truncated to fit) ----
    heading("Conversion Notes")
    pdf.set_font("Helvetica", "", 8)
    clean = _ascii(explanation)
    for md_line in clean.split("\n"):
        stripped = md_line.strip()
        if not stripped or (stripped.startswith("|") and "--" in stripped):
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
            pdf.set_font("Helvetica", "B", 8)
            pdf.multi_cell(W, 3.5, stripped, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
        else:
            pdf.multi_cell(W, 3.5, stripped, new_x="LMARGIN", new_y="NEXT")
        if pdf.page_no() >= 3 and pdf.get_y() > 260:
            pdf.multi_cell(W, 3.5, "... (truncated for brevity)", new_x="LMARGIN", new_y="NEXT")
            break

    return bytes(pdf.output())
